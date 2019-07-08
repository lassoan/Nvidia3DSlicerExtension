import os
import vtk, qt, ctk, slicer
import logging
from SegmentEditorEffects import *
import httplib
import urllib
import json
import mimetypes
import cgi
import SimpleITK as sitk
import sitkUtils
import tempfile
import os
import numpy as np
import vtkSegmentationCorePython as vtkSegmentationCore


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect):
    """This effect uses Watershed algorithm to partition the input volume"""

    def __init__(self, scriptedEffect):
        scriptedEffect.name = 'Nvidia AIAA'
        scriptedEffect.perSegment = False  # this effect operates on all segments at once (not on a single selected segment)
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

        self.extremePoints = dict()
        self.annotationPointSet = []
        self.models = dict()

        # Effect-specific members
        self.segmentMarkupNode = None
        self.segmentMarkupNodeObservers = []

    def clone(self):
        # It should not be necessary to modify this method
        import qSlicerSegmentationsEditorEffectsPythonQt as effects
        clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
        clonedEffect.setPythonSource(__file__.replace('\\', '/'))
        return clonedEffect

    def icon(self, name='SegmentEditorEffect.png'):
        # It should not be necessary to modify this method
        iconPath = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """Use NVIDIA AI-Assisted features for segmentation and annotation."""

    def setupOptionsFrame(self):
        nvidiaFormLayout = qt.QFormLayout()

        ##################################################
        # AIAA Server + Fetch/Refresh Models
        nvidiaFormLayout.addRow(qt.QLabel())
        aiaaGroupBox = qt.QGroupBox("AI-Assisted Annotation Server: ")
        aiaaGroupLayout = qt.QFormLayout(aiaaGroupBox)
        self.serverIP = qt.QLineEdit("10.110.45.66")
        self.serverPort = qt.QLineEdit("5678")
        self.filterByLabel = qt.QCheckBox("Filter By Label")
        self.modelsButton = qt.QPushButton("Fetch Models")

        self.filterByLabel.setChecked(True)

        aiaaGroupLayout.addRow("Server IP: ", self.serverIP)
        aiaaGroupLayout.addRow("Server Port: ", self.serverPort)
        aiaaGroupLayout.addRow(self.filterByLabel)
        aiaaGroupLayout.addRow(self.modelsButton)

        aiaaGroupBox.setLayout(aiaaGroupLayout)
        nvidiaFormLayout.addRow(aiaaGroupBox)
        ##################################################

        ##################################################
        # Segmentation
        nvidiaFormLayout.addRow(qt.QLabel())
        segGroupBox = qt.QGroupBox("Auto Segmentation: ")
        segGroupLayout = qt.QFormLayout(segGroupBox)
        self.segmentationModelSelector = qt.QComboBox()
        self.segmentationButton = qt.QPushButton(" Run Segmentation")
        self.segmentationButton.setIcon(self.icon('nvidia-icon.png'))
        self.segmentationButton.setEnabled(False)

        # self.segmentationModelSelector.addItems(['segmentation_ct_spleen', 'segmentation_ct_liver_and_tumor'])
        self.segmentationModelSelector.setToolTip("Pick the input Segmentation model")

        segGroupLayout.addRow("Model: ", self.segmentationModelSelector)
        segGroupLayout.addRow(self.segmentationButton)

        segGroupBox.setLayout(segGroupLayout)
        ##################################################

        ##################################################
        # Annotation
        annGroupBox = qt.QGroupBox("Annotation: ")
        annGroupLayout = qt.QFormLayout(annGroupBox)

        # Fiducial Placement widget
        self.fiducialPlacementToggle = slicer.qSlicerMarkupsPlaceWidget()
        self.fiducialPlacementToggle.setMRMLScene(slicer.mrmlScene)
        self.fiducialPlacementToggle.placeMultipleMarkups = self.fiducialPlacementToggle.ForcePlaceMultipleMarkups
        self.fiducialPlacementToggle.buttonsVisible = False
        self.fiducialPlacementToggle.show()
        self.fiducialPlacementToggle.placeButton().show()
        self.fiducialPlacementToggle.deleteButton().show()

        # Edit surface button
        self.annoEditButton = qt.QPushButton()
        self.annoEditButton.setIcon(self.icon('edit-icon.png'))
        self.annoEditButton.objectName = self.__class__.__name__ + 'Edit'
        self.annoEditButton.setToolTip("Edit the previously placed group of fiducials.")

        fiducialActionLayout = qt.QHBoxLayout()
        fiducialActionLayout.addWidget(self.fiducialPlacementToggle)
        fiducialActionLayout.addWidget(self.annoEditButton)

        self.annotationModelSelector = qt.QComboBox()
        self.dextr3DButton = qt.QPushButton(" Run DExtr3D")
        self.dextr3DButton.setIcon(self.icon('nvidia-icon.png'))
        self.dextr3DButton.setEnabled(False)

        # self.annotationModelSelector.addItems(['annotation_ct_spleen'])
        self.annotationModelSelector.setToolTip("Pick the input Annotation model")

        annGroupLayout.addRow("Model: ", self.annotationModelSelector)
        annGroupLayout.addRow(fiducialActionLayout)
        annGroupLayout.addRow(self.dextr3DButton)

        annGroupBox.setLayout(annGroupLayout)
        ##################################################
        aiaaAction = qt.QHBoxLayout()
        aiaaAction.addWidget(segGroupBox)
        aiaaAction.addWidget(annGroupBox)
        nvidiaFormLayout.addRow(aiaaAction)

        self.scriptedEffect.addOptionsWidget(nvidiaFormLayout)

        ##################################################
        # connections
        self.modelsButton.connect('clicked(bool)', self.onClickModels)
        self.segmentationButton.connect('clicked(bool)', self.onClickSegmentation)
        self.annoEditButton.connect('clicked(bool)', self.onClickEditPoints)
        self.fiducialPlacementToggle.placeButton().clicked.connect(self.onFiducialPlacementToggleChanged)
        self.dextr3DButton.connect('clicked(bool)', self.onClickAnnotation)
        ##################################################

    def getActiveLabel(self):
        node = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        id = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        name = node.GetSegmentation().GetSegment(id).GetName()
        return name

    def onClickModels(self):
        logic = AIAALogic(self.serverIP.text, int(self.serverPort.text))
        label = self.getActiveLabel()
        logging.info('Active Label: {}'.format(label))
        models = json.loads(logic.list_models(label if self.filterByLabel.checked else None))

        self.segmentationModelSelector.clear()
        self.annotationModelSelector.clear()
        for model in models:
            model_name = model['name']
            model_type = model['type']
            logging.info('{} = {}'.format(model_name, model_type))
            self.models[model_name] = model

            if model_type == 'segmentation':
                self.segmentationModelSelector.addItem(model_name)
            else:
                self.annotationModelSelector.addItem(model_name)

        self.segmentationButton.enabled = self.segmentationModelSelector.count > 0
        self.onClickEditPoints()
        self.updateGUIFromMRML()

        msg = ''
        msg += '-----------------------------------------------------\t\n'
        if self.filterByLabel.checked:
            msg += 'Using Label: \t\t' + label + '\t\n'
        msg += 'Total Models Loaded: \t' + str(len(models)) + '\t\n'
        msg += '-----------------------------------------------------\t\n'
        msg += 'Segmentation Models: \t' + str(self.segmentationModelSelector.count) + '\t\n'
        msg += 'Annotation Models: \t' + str(self.annotationModelSelector.count) + '\t\n'
        msg += '-----------------------------------------------------\t\n'
        qt.QMessageBox.information(slicer.util.mainWindow(), 'NVIDIA AIAA', msg)

    def updateSegmentationMask(self, json, in_file):
        if in_file is None:
            return False

        labelImage = sitk.ReadImage(in_file)
        # cc = sitk.ConnectedComponentImageFilter()
        # labelCC = cc.Execute(sitk.Cast(labelImage, sitk.sitkUInt8))
        labelmapVolumeNode = sitkUtils.PushVolumeToSlicer(labelImage, None)

        newSegmentLabelmap = vtkSegmentationCore.vtkOrientedImageData()
        newSegmentLabelmap.DeepCopy(labelmapVolumeNode.GetImageData())

        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        selectedSegmentId = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        slicer.vtkSlicerSegmentationsModuleLogic.SetBinaryLabelmapToSegment(
            newSegmentLabelmap,
            segmentationNode,
            selectedSegmentId,
            slicer.vtkSlicerSegmentationsModuleLogic.MODE_REPLACE,
            newSegmentLabelmap.GetExtent())

        segment = segmentationNode.GetSegmentation().GetSegment(selectedSegmentId)
        points = None if json is None else json.get('points')
        logging.info('Extreme Points: {}'.format(points))
        if points is not None:
            segment.SetTag("DExtr3DExtremePoints", points)

        self.extremePoints[segment.GetName()] = json
        os.unlink(in_file)
        return True

    def onClickSegmentation(self):
        logic = AIAALogic(self.serverIP.text, int(self.serverPort.text))
        model = self.segmentationModelSelector.currentText
        label = self.getActiveLabel()
        logging.info('Run Segmentation for model: {} for label: {}'.format(model, label))

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

        inputVolume = self.scriptedEffect.parameterSetNode().GetMasterVolumeNode()
        json, result_file = logic.segmentation(model, inputVolume)
        result = 'SUCCESS' if self.updateSegmentationMask(json, result_file) is True else 'FAILED'

        if result is 'SUCCESS':
            self.onClickEditPoints()
            self.updateGUIFromMRML()

        qt.QApplication.restoreOverrideCursor()
        qt.QMessageBox.information(
            slicer.util.mainWindow(),
            'NVIDIA AIAA',
            'Run segmentation for (' + model + '): ' + result + '\t')

    def onClickAnnotation(self):
        logic = AIAALogic(self.serverIP.text, int(self.serverPort.text))
        model = self.annotationModelSelector.currentText
        label = self.getActiveLabel()
        logging.info('Run Annotation for model: {} for label: {}'.format(model, label))

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

        inputVolume = self.scriptedEffect.parameterSetNode().GetMasterVolumeNode()
        modelInfo = self.models.get(model)
        json, result_file = logic.dextr3d(model, self.annotationPointSet, inputVolume, modelInfo)
        result = 'SUCCESS' if self.updateSegmentationMask(json, result_file) is True else 'FAILED'

        if result is 'SUCCESS':
            self.onClickEditPoints()
            self.updateGUIFromMRML()

        qt.QApplication.restoreOverrideCursor()
        qt.QMessageBox.information(
            slicer.util.mainWindow(),
            'NVIDIA AIAA',
            'Run dextr3D for (' + model + '): ' + result + '\t')

    def onClickEditPoints(self):
        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        segment = segmentationNode.GetSegmentation().GetSegment(segmentID)

        self.segmentMarkupNode.RemoveAllMarkups()

        fPosStr = vtk.mutable("")
        segment.GetTag("DExtr3DExtremePoints", fPosStr)
        logging.info('Extreme points are: '.format(fPosStr))

        if fPosStr is not None and len(fPosStr) > 0:
            points = json.loads(str(fPosStr))
            for p in points:
                logging.info('Extreme Point: {}'.format(p))
                self.segmentMarkupNode.AddFiducialFromArray(p)

            self.annoEditButton.setEnabled(False)

    def reset(self):
        if self.fiducialPlacementToggle.placeModeEnabled:
            self.fiducialPlacementToggle.setPlaceModeEnabled(False)

        if not self.annoEditButton.isEnabled():
            self.annoEditButton.setEnabled(True)

        if self.segmentMarkupNode:
            slicer.mrmlScene.RemoveNode(self.segmentMarkupNode)
            self.setAndObserveSegmentMarkupNode(None)

    def activate(self):
        self.scriptedEffect.showEffectCursorInSliceView = False

        # Create empty markup fiducial node
        if not self.segmentMarkupNode:
            self.createNewMarkupNode()
            self.fiducialPlacementToggle.setCurrentNode(self.segmentMarkupNode)
            self.setAndObserveSegmentMarkupNode(self.segmentMarkupNode)
            self.fiducialPlacementToggle.setPlaceModeEnabled(False)

        self.updateGUIFromMRML()

    def deactivate(self):
        self.reset()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def setMRMLDefaults(self):
        pass

    def updateGUIFromMRML(self):
        if self.segmentMarkupNode:
            self.dextr3DButton.setEnabled(self.segmentMarkupNode.GetNumberOfFiducials() >= 6)
        else:
            self.dextr3DButton.setEnabled(False)

        segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()
        segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
        if segmentID and segmentationNode:
            segment = segmentationNode.GetSegmentation().GetSegment(segmentID)
            self.annoEditButton.setVisible(segment.HasTag("DExtr3DExtremePoints"))

    def updateMRMLFromGUI(self):
        pass

    def onFiducialPlacementToggleChanged(self):
        if self.fiducialPlacementToggle.placeButton().isChecked():
            # Create empty markup fiducial node
            if self.segmentMarkupNode is None:
                self.createNewMarkupNode()
                self.fiducialPlacementToggle.setCurrentNode(self.segmentMarkupNode)

    def createNewMarkupNode(self):
        # Create empty markup fiducial node
        if self.segmentMarkupNode is None:
            displayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsDisplayNode")
            displayNode.SetTextScale(0)
            self.segmentMarkupNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
            self.segmentMarkupNode.SetName('A')
            self.segmentMarkupNode.SetAndObserveDisplayNodeID(displayNode.GetID())
            self.setAndObserveSegmentMarkupNode(self.segmentMarkupNode)
            self.updateGUIFromMRML()

    def setAndObserveSegmentMarkupNode(self, segmentMarkupNode):
        if segmentMarkupNode == self.segmentMarkupNode and self.segmentMarkupNodeObservers:
            # no change and node is already observed
            return

        # Remove observer to old parameter node
        if self.segmentMarkupNode and self.segmentMarkupNodeObservers:
            for observer in self.segmentMarkupNodeObservers:
                self.segmentMarkupNode.RemoveObserver(observer)
            self.segmentMarkupNodeObservers = []

        # Set and observe new parameter node
        self.segmentMarkupNode = segmentMarkupNode
        if self.segmentMarkupNode:
            if (slicer.app.majorVersion >= 5) or (slicer.app.majorVersion >= 4 and slicer.app.minorVersion >= 11):
                eventIds = [vtk.vtkCommand.ModifiedEvent,
                            slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                            slicer.vtkMRMLMarkupsNode.PointAddedEvent,
                            slicer.vtkMRMLMarkupsNode.PointRemovedEvent]
            else:
                eventIds = [vtk.vtkCommand.ModifiedEvent]
            for eventId in eventIds:
                self.segmentMarkupNodeObservers.append(
                    self.segmentMarkupNode.AddObserver(eventId, self.onSegmentMarkupNodeModified))

        # Update GUI
        self.updateModelFromSegmentMarkupNode()

    def onSegmentMarkupNodeModified(self, observer, eventid):
        self.updateModelFromSegmentMarkupNode()
        self.updateGUIFromMRML()

    def updateModelFromSegmentMarkupNode(self):
        if not self.segmentMarkupNode:
            return

        # Run Annotation Logic
        logging.info('Added Point - Pre-Check Annotation Logic here...')
        # get fiducial positions as space-separated list

        n = self.segmentMarkupNode.GetNumberOfFiducials()
        self.annotationPointSet = []
        for i in range(n):
            coord = [0.0, 0.0, 0.0]
            self.segmentMarkupNode.GetNthFiducialPosition(i, coord)
            self.annotationPointSet.append(coord)
        logging.info('Current Fiducials-Points: {}'.format(self.annotationPointSet))

    def interactionNodeModified(self, interactionNode):
        # Override default behavior: keep the effect active if markup placement mode is activated
        pass


class AIAALogic():
    def __init__(self, server_host='0.0.0.0', server_port=5000, server_version='v1'):
        self.server_url = server_host + ':' + str(server_port)
        self.server_version = server_version
        logging.info('Using URI: {}'.format(self.server_url))

    def list_models(self, label=None):
        conn = httplib.HTTPConnection(self.server_url)
        selector = '/' + self.server_version + '/models'
        if label is not None and len(label) > 0:
            selector += '?label=' + urllib.quote_plus(label)

        logging.info('Using Selector: {}'.format(selector))
        conn.request('GET', selector)
        response = conn.getresponse()
        return response.read()

    def segmentation(self, model, inputVolume):
        logging.info('Preparing for Segmentation Action')
        in_file = tempfile.NamedTemporaryFile(suffix='.nii.gz').name

        slicer.util.saveNode(inputVolume, in_file)
        logging.info('Saved Input Node into: {}'.format(in_file))

        selector = '/' + self.server_version + '/segmentation?model=' + urllib.quote_plus(model)
        fields = {'params': '{}'}
        files = {'datapoint': in_file}

        logging.info('Using Selector: {}'.format(selector))
        logging.info('Using Fields: {}'.format(fields))
        logging.info('Using Files: {}'.format(files))

        form, files = self.post_multipart(selector, fields, files)

        result_file = None
        if len(files) > 0:
            fname = files.keys()[0]
            logging.info('Saving segmentation result: {}'.format(fname))
            with tempfile.NamedTemporaryFile(suffix='.nii.gz', delete=False) as f:
                f.write(files[fname])
                result_file = f.name

        os.unlink(in_file)
        return form, result_file

    def dextr3d(self, model, pointset, inputVolume, modelInfo):
        logging.info('Preparing for Annotation/Dextr3D Action')
        in_file = tempfile.NamedTemporaryFile(suffix='.nii.gz').name

        slicer.util.saveNode(inputVolume, in_file)
        logging.info('Saved Input Node into: {}'.format(in_file))

        # Pre Process
        pad = 20
        roi_size = '128x128x128'
        if modelInfo is not None:
            pad = modelInfo['padding']
            roi_size = 'x'.join(map(str, modelInfo['roi']))

        cropped_file = tempfile.NamedTemporaryFile(suffix='.nii.gz').name
        points, crop = AIAALogic.image_pre_process(in_file, cropped_file, pointset, pad, roi_size)

        selector = '/' + self.server_version + '/dextr3d?model=' + urllib.quote_plus(model)
        params = dict()
        params['points'] = json.dumps(points)

        fields = {'params': json.dumps(params)}
        files = {'datapoint': cropped_file}

        logging.info('Using Selector: {}'.format(selector))
        logging.info('Using Fields: {}'.format(fields))
        logging.info('Using Files: {}'.format(files))

        form, files = self.post_multipart(selector, fields, files)

        # Post Process
        result_file = None
        if len(files) > 0:
            fname = files.keys()[0]
            logging.info('Saving segmentation result: {}'.format(fname))
            with tempfile.NamedTemporaryFile(suffix='.nii.gz', delete=False) as f:
                f.write(files[fname])
                cropped_out_file = f.name

            result_file = tempfile.NamedTemporaryFile(suffix='.nii.gz').name
            AIAALogic.image_post_processing(cropped_out_file, result_file, crop, in_file)

        os.unlink(in_file)
        os.unlink(cropped_file)
        os.unlink(cropped_out_file)
        return form, result_file

    @staticmethod
    def resample_image(itk_image, out_size, linear):
        spacing = itk_image.GetSpacing()
        size = itk_image.GetSize()

        out_spacing = []
        for i in range(3):
            out_spacing.append(float(spacing[i]) * float(size[i]) / float(out_size[i]))

        resample = sitk.ResampleImageFilter()
        resample.SetOutputSpacing(out_spacing)
        resample.SetSize(out_size)
        resample.SetOutputDirection(itk_image.GetDirection())
        resample.SetOutputOrigin(itk_image.GetOrigin())
        resample.SetTransform(sitk.Transform())
        resample.SetDefaultPixelValue(itk_image.GetPixelIDValue())

        if linear:
            resample.SetInterpolator(sitk.sitkLinear)
        else:
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
        return resample.Execute(itk_image)

    @staticmethod
    def image_pre_process(input_file, output_file, point_set, pad, roi_size):
        itk_image = sitk.ReadImage(input_file)
        spacing = itk_image.GetSpacing()
        image_size = itk_image.GetSize()

        target_size = tuple(map(int, roi_size.split('x')))
        points = np.asanyarray(point_set)

        # get bounding box
        x1 = int(max(0, np.min(points[::, 0]) - int(pad / spacing[0])))
        x2 = int(min(image_size[0], np.max(points[::, 0]) + int(pad / spacing[0])))
        y1 = int(max(0, np.min(points[::, 1]) - int(pad / spacing[1])))
        y2 = int(min(image_size[1], np.max(points[::, 1]) + int(pad / spacing[1])))
        z1 = int(max(0, np.min(points[::, 2]) - int(pad / spacing[2])))
        z2 = int(min(image_size[2], np.max(points[::, 2]) + int(pad / spacing[2])))
        crop = [[x1, x2], [y1, y2], [z1, z2]]

        # crop
        points[::, 0] = points[::, 0] - x1
        points[::, 1] = points[::, 1] - y1
        points[::, 2] = points[::, 2] - z1

        cropped_image = itk_image[x1:x2, y1:y2, z1:z2]
        cropped_size = cropped_image.GetSize()

        # resize
        ratio = np.divide(np.asanyarray(target_size, dtype=np.float), np.asanyarray(cropped_size, dtype=np.float))
        out_image = AIAALogic.resample_image(cropped_image, target_size, True)

        sitk.WriteImage(out_image, output_file, True)

        points[::, 0] = points[::, 0] * ratio[0]
        points[::, 1] = points[::, 1] * ratio[1]
        points[::, 2] = points[::, 2] * ratio[2]
        return points.astype(int).tolist(), crop

    @staticmethod
    def image_post_processing(input_file, output_file, crop, orig_file):
        itk_image = sitk.ReadImage(input_file)
        orig_crop_size = [crop[0][1] - crop[0][0], crop[1][1] - crop[1][0], crop[2][1] - crop[2][0]]
        resize_image = AIAALogic.resample_image(itk_image, orig_crop_size, False)

        orig_image = sitk.ReadImage(orig_file)
        orig_size = orig_image.GetSize()

        image = sitk.GetArrayFromImage(resize_image)
        result = np.zeros(orig_size[::-1], np.uint8)
        result[crop[2][0]:crop[2][1], crop[1][0]:crop[1][1], crop[0][0]:crop[0][1]] = image

        itk_result = sitk.GetImageFromArray(result)
        itk_result.SetDirection(orig_image.GetDirection())
        itk_result.SetSpacing(orig_image.GetSpacing())

        sitk.WriteImage(itk_result, output_file, True)

    def post_multipart(self, selector, fields, files):
        content_type, body = self.encode_multipart_formdata(fields, files)
        h = httplib.HTTP(self.server_url)
        h.putrequest('POST', selector)
        h.putheader('content-type', content_type)
        h.putheader('content-length', str(len(body)))
        h.endheaders()
        h.send(body)

        errcode, errmsg, headers = h.getreply()
        logging.info('Error Code: {}'.format(errcode))
        logging.info('Error Message: {}'.format(errmsg))
        logging.info('Headers: {}'.format(headers))

        form, files = self.parse_multipart(h.file, headers)
        logging.info('Response FORM: {}'.format(form))
        logging.info('Response FILES: {}'.format(files.keys()))
        return form, files

    def encode_multipart_formdata(self, fields, files):
        LIMIT = '----------lImIt_of_THE_fIle_eW_$'
        CRLF = '\r\n'
        L = []
        for (key, value) in fields.items():
            L.append('--' + LIMIT)
            L.append('Content-Disposition: form-data; name="%s"' % key)
            L.append('')
            L.append(value)
        for (key, filename) in files.items():
            L.append('--' + LIMIT)
            L.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, filename))
            L.append('Content-Type: %s' % self.get_content_type(filename))
            L.append('')
            with open(filename, mode='rb') as f:
                data = f.read()
                L.append(data)
        L.append('--' + LIMIT + '--')
        L.append('')
        body = CRLF.join(L)
        content_type = 'multipart/form-data; boundary=%s' % LIMIT
        return content_type, body

    def get_content_type(self, filename):
        return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    def parse_multipart(self, fp, headers):
        fs = cgi.FieldStorage(
            fp=fp,
            environ={'REQUEST_METHOD': 'POST'},
            headers=headers,
            keep_blank_values=True
        )
        form = {}
        files = {}
        for f in fs.list:
            if f.filename:
                files[f.filename] = f.value
            else:
                form[f.name] = f.value
        return form, files