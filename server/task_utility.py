# coding=utf-8

import datetime
import itertools
import mimetypes
import operator
import os
import json

import cherrypy
from girder.api import access
from girder.api.rest import Resource, RestException, loadmodel
from girder.api.describe import Description
from girder.constants import AccessType
from girder.models.model_base import AccessException

from .model_utility import getCollection, getFoldersForCollection,\
    getFolder, getItemsInFolder, getUDAuser
from .provision_utility import getOrCreateUDAFolder


class UDAResource(Resource):
    def __init__(self, plugin_root_dir):
        self.resourceName = 'uda'
        self.plugin_root_dir = plugin_root_dir

        self.route('GET', ('task',), self.taskList)
        self.route('POST', ('task', 'qc', ':folder_id', 'complete'), self.p0TaskComplete)
        self.route('GET', ('task', 'markup', ':item_id'), self.p1or2TaskDetail)
        self.route('POST', ('task', 'markup', ':item_id', 'complete'), self.p1TaskComplete)
        self.route('GET', ('task', 'map', ':item_id'), self.p1or2TaskDetail)
        self.route('POST', ('task', 'map', ':item_id', 'complete'), self.p2TaskComplete)


    def _requireCollectionAccess(self, collection_name):
        collection = self.model('collection').findOne({'name': collection_name})
        user = self.getCurrentUser()
        self.model('collection').requireAccess(collection, user, AccessType.READ)


    def _countImagesInCollection(self, collectionName):
        collection = getCollection(collectionName)
        total_len = sum(len(getItemsInFolder(folder)) for folder in getFoldersForCollection(collection))
        return total_len

    @access.user
    def taskList(self, params):
        result = list()

        # TODO: make this a global constant somewhere
        PHASE_TASK_URLS = {
            'Phase 0': '/uda/task/p0',
            'Phase 1a': '/uda/task/p1a',
            'Phase 1b': '/uda/task/p1b',
            'Phase 1c': '/uda/task/p1c',
            'Phase 2': '/uda/task/p2'
        }
        for phase_name, task_url in sorted(PHASE_TASK_URLS.iteritems()):
            try:
                self._requireCollectionAccess(phase_name)
            except AccessException:
                continue

            result.append({
                'phase': phase_name,
                'count': self._countImagesInCollection(phase_name),
                'url': task_url,
            })

        return result

    taskList.description = (
        Description('List available tasks.')
        .responseClass('UDA')
        .errorResponse())


    @access.user
    @loadmodel(map={'folder_id': 'folder'}, model='folder', level=AccessType.READ)
    def p0TaskComplete(self, folder):
        # verify user's access to folder and phase
        phase0_collection = self.model('collection').findOne({'name': 'Phase 0'})
        self.model('collection').requireAccess(phase0_collection, self.getCurrentUser(), AccessType.READ)
        if folder['baseParentId'] != phase0_collection['_id']:
            raise RestException('Folder %s is not inside Phase 0' % folder['_id'])

        contents = json.loads(cherrypy.request.body.read())

        # verify that all images are in folder
        flagged_image_items = [
            self.model('item').load(image_item_id, force=True)
            for image_item_id in contents['flagged']
        ]
        for image_item in flagged_image_items:
            if image_item['folderId'] != folder['_id']:
                raise RestException('Flagged image %s is not inside folder %s' % (image_item['_id'], folder['_id']))
        good_image_items = [
            self.model('item').load(image_item_id, force=True)
            for image_item_id in contents['good']
        ]
        for image_item in good_image_items:
            if image_item['folderId'] != folder['_id']:
                raise RestException('Good image %s is not inside folder %s' % (image_item['_id'], folder['_id']))


        # move flagged images into flagged folder, set QC metadata
        phase0_flagged_images = getFolder(phase0_collection, 'flagged')
        # TODO: create "flagged" if not present?
        for image_item in flagged_image_items:
            qc_metadata = {
                'qc_user': self.getCurrentUser()['_id'],
                'qc_result': 'flagged',
                'qc_folder_id': folder['_id']
            }
            self.model('item').setMetadata(image_item, qc_metadata)
            self.model('item').move(image_item, phase0_flagged_images)

        # move good images into phase 1a folder
        phase1a_collection = self.model('collection').findOne({'name': 'Phase 1a'})
        phase1a_images = getOrCreateUDAFolder(
            name=folder['name'],
            description=folder['description'],
            parent=phase1a_collection,
            parent_type='collection'
        )
        for image_item in good_image_items:
            qc_metadata = {
                'qc_user': self.getCurrentUser()['_id'],
                'qc_result': 'ok',
                'qc_folder_id': folder['_id'],
                'qc_stop_time': datetime.datetime.utcnow(),
            }
            self.model('item').setMetadata(image_item, qc_metadata)
            self.model('item').move(image_item, phase1a_images)

        return {'status': 'success'}

    p0TaskComplete.description = (
        Description('Complete a Phase 0 (qc) task.')
        .responseClass('UDA')
        .param('details', 'JSON details of images to be QC\'d.', paramType='body')
        .errorResponse())


    @access.user
    @loadmodel(map={'item_id': 'item'}, model='item', level=AccessType.READ)
    def p1or2TaskDetail(self, item, params):
        # verify item is in the correct phase and user has access
        collection = self.model('collection').load(
            id=item['baseParentId'],
            level=AccessType.READ,
            user=self.getCurrentUser()
        )
        phase_name = collection['name']
        if not (phase_name.startswith('Phase 1') or phase_name == 'Phase 2'):
            raise RestException('Item %s is not inside Phase 1 or Phase 2' % item['_id'])

        return_dict = {
            'phase': phase_name,
            'items': [item],
        }

        # if necessary, load annotations from previous phase
        PREVIOUS_PHASE_CODES = {
            'Phase 1b': 'p1a',
            'Phase 1c': 'p1b',
            'Phase 2': 'p1c'
        }
        previous_phase_code = PREVIOUS_PHASE_CODES.get(phase_name)
        if previous_phase_code:
            return_dict['loadAnnotation'] = True

            previous_phase_annotation_file_name_ending = '-%s.json' % previous_phase_code
            for item_file in sorted(
                    self.model('item').childFiles(item, limit=0),
                    key=operator.itemgetter('created'),
                    reverse=True
            ):
                if item_file['name'].endswith(previous_phase_annotation_file_name_ending):
                    item_file_generator = self.model('file').download(item_file, headers=False)
                    previous_phase_annotation = json.loads(''.join(item_file_generator()))
                    return_dict['annotation'] = previous_phase_annotation[previous_phase_code]['steps']
                    break
            else:
                # TODO: no file found, raise error
                pass

            if phase_name == 'Phase 2':
                phase2_variables_path = os.path.join(self.plugin_root_dir, 'custom', 'config', 'phase2-variables.json')
                with open(phase2_variables_path, 'r') as phase2_variables_file:
                    return_dict['variables'] = json.load(phase2_variables_file)
        else:
            return_dict['loadAnnotation'] = False

        # include static phase config
        phase_config_file_name = '%s.json' % phase_name.replace(' ', '').lower()
        phase_config_file_path = os.path.join(self.plugin_root_dir, 'custom', 'config', phase_config_file_name)
        with open(phase_config_file_path, 'r') as phase_config_file:
            return_dict['decision_tree'] = json.load(phase_config_file)

        return return_dict

    p1or2TaskDetail.description = (
        Description('Get details of a Phase 1 (markup) or Phase 2 (map) task.')
        .responseClass('UDA')
        .param('item_id', 'The item ID.', paramType='path')
        .errorResponse())


    @access.user
    def p1TaskComplete(self, item_id, params):
        markup_str = cherrypy.request.body.read()
        markup_dict = json.loads(markup_str)

        phase_handlers = {
            # phase_full_lower: (phase_acronym, next_phase_full)
            'Phase 1a': ('p1a', 'Phase 1b'),
            'Phase 1b': ('p1b', 'Phase 1c'),
            'Phase 1c': ('p1c', 'Phase 2'),
        }
        try:
            phase_acronym, next_phase_full = phase_handlers[markup_dict['phase']]
        except KeyError:
            # TODO: send the proper error code on failure
            raise
        else:
            self._requireCollectionAccess(markup_dict['phase'])
            result = self._handlePhaseCore(markup_dict, phase_acronym, next_phase_full)

        return {'status': result}

    p1TaskComplete.description = (
        Description('Complete a Phase 1 (markup) task.')
        .responseClass('UDA')
        .param('item_id', 'The item ID.', paramType='path')
        .errorResponse())


    @access.user
    def p2TaskComplete(self, item_id, params):
        self._requireCollectionAccess('Phase 2')
        markup_str = cherrypy.request.body.read()
        markup_dict = json.loads(markup_str)

        # TODO: auto-create "Complete" collection owned by "udastudy"
        result = self._handlePhaseCore(markup_dict, 'p2', 'Complete')

        return {'status': result}

    p2TaskComplete.description = (
        Description('Complete a Phase 2 (map) task.')
        .responseClass('UDA')
        .param('item_id', 'The item ID.', paramType='path')
        .errorResponse())


    def _handlePhaseCore(self, markup_dict, phase_acronym, next_phase_full):
        item_name_base = markup_dict['image']['name'].split('.t')[0]

        item_metadata = {
            '%s_user' % phase_acronym: markup_dict['user']['_id'],
            '%s_result' % phase_acronym: 'ok',
            '%s_folder_id' % phase_acronym: markup_dict['image']['folderId'],
            '%s_start_time' % phase_acronym: markup_dict['taskstart'],
            '%s_stop_time' % phase_acronym: markup_dict['taskend'],
        }

        markup_json = dict()
        markup_json[phase_acronym] = {
            'user': markup_dict['user'],
            'image': markup_dict['image'],
            'result': item_metadata
        }

        if phase_acronym in ['p1a', 'p1b', 'p1c']:
            markup_json[phase_acronym]['steps'] = markup_dict['steps']

            # grab and remove the b64 png from the dictionary
            png_b64string = markup_dict['steps']['2']['markup']['features'][0]['properties']['parameters'].pop('rgb')
            # remote the initial data uri details
            png_b64string_trim = png_b64string[22:]

            # grab and remove the b64 png from the dictionary
            png_tiles_b64string = markup_dict['steps']['2']['markup']['features'][0]['properties']['parameters'].pop('tiles')
            # remote the initial data uri details
            png_tiles_b64string_trim = png_tiles_b64string[22:]

        elif phase_acronym == 'p2':
            markup_json[phase_acronym]['user_annotation'] = markup_dict['user_annotation']
            markup_json[phase_acronym]['markup_model'] = markup_dict['markup_model']
            # TODO: dereference annotation_options

        # add to existing item
        # TODO: get item_id from URL, instead of within markup_dict
        image_item = self.model('item').load(markup_dict['image']['_id'], force=True)
        self.model('item').setMetadata(image_item, item_metadata)

        # move item to folder in next collection
        original_folder = self.model('folder').load(markup_dict['image']['folderId'], force=True)

        next_phase_folder = getOrCreateUDAFolder(
            name=original_folder['name'],
            description=original_folder['description'],
            parent=getCollection(next_phase_full),
            parent_type='collection'
        )

        self.model('item').move(image_item, next_phase_folder)

        self._createFileFromData(
            image_item,
            json.dumps(markup_json),
            '%s-%s.json' % (item_name_base, phase_acronym)
        )

        if phase_acronym in ['p1a', 'p1b', 'p1c']:
            self._createFileFromData(
                image_item,
                png_b64string_trim.decode('base64'),
                '%s-%s.png' % (item_name_base, phase_acronym)
            )

            self._createFileFromData(
                image_item,
                png_tiles_b64string_trim.decode('base64'),
                '%s-tile-%s.png' % (item_name_base, phase_acronym)
            )

        return 'success'


    def _createFileFromData(self, item, data, filename):
        # TODO: overwrite existing files if present, using provenance to keep old files
        upload = self.model('upload').createUpload(
            getUDAuser(),
            filename,
            'item', item,
            len(data),
            mimetypes.guess_type(filename)[0]
        )
        self.model('upload').handleChunk(upload, data)


class TaskHandler(Resource):
    def __init__(self, plugin_root_dir):
        self.resourceName = 'task'
        self.plugin_root_dir = plugin_root_dir

        self.route('GET', (), self.taskDashboard)
        self.route('GET', ('p0',), self.p0TaskRedirect)
        self.route('GET', ('p1a',), self.p1aTaskRedirect)
        self.route('GET', ('p1b',), self.p1bTaskRedirect)
        self.route('GET', ('p1c',), self.p1cTaskRedirect)
        self.route('GET', ('p2',), self.p2TaskRedirect)
        # TODO: cookieAuth decorator


    @access.public
    def taskDashboard(self, params):
        return cherrypy.lib.static.serve_file(os.path.join(self.plugin_root_dir, 'custom', 'task.html'))
    taskDashboard.cookieAuth = True


    def _largestFolderWithItems(self, phase_name):
        collection = self.model('collection').findOne({'name': phase_name})
        self.model('collection').requireAccess(
            doc=collection,
            user=self.getCurrentUser(),
            level=AccessType.READ
        )

        folders_with_items = (
            (folder, getItemsInFolder(folder))
            for folder in getFoldersForCollection(collection))
        folders_with_items = itertools.ifilter(lambda x: len(x[1]), folders_with_items)
        folders_with_items = sorted(folders_with_items, key=lambda x: [1], reverse=True)

        if folders_with_items:
            folder, items = folders_with_items[0]
            return folder, items
        else:
            return None, None


    def _taskRedirect(self, phase_name, url_format):
        folder, items = self._largestFolderWithItems(phase_name)
        if folder is None:
            return 'no tasks for user'

        redirect_url = url_format % {
            'folder_id': folder['_id'],
            'item_id': items[0]['_id']
        }
        raise cherrypy.HTTPRedirect(redirect_url, status=307)


    @access.user
    def p0TaskRedirect(self, params):
        return self._taskRedirect('Phase 0', '/uda/qc/%(folder_id)s')
    p0TaskRedirect.cookieAuth = True


    @access.user
    def p1aTaskRedirect(self, params):
        return self._taskRedirect('Phase 1a', '/uda/annotate/%(item_id)s')
    p1aTaskRedirect.cookieAuth = True


    @access.user
    def p1bTaskRedirect(self, params):
        return self._taskRedirect('Phase 1b', '/uda/annotate/%(item_id)s')
    p1bTaskRedirect.cookieAuth = True


    @access.user
    def p1cTaskRedirect(self, params):
        return self._taskRedirect('Phase 1c', '/uda/annotate/%(item_id)s')
    p1cTaskRedirect.cookieAuth = True


    @access.user
    def p2TaskRedirect(self, params):
        return self._taskRedirect('Phase 2', '/uda/map/%(item_id)s')
    p2TaskRedirect.cookieAuth = True
