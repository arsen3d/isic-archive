#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import csv
from cStringIO import StringIO
import functools
import itertools

import cherrypy
import six

from girder.api import access
from girder.api.rest import RestException, loadmodel, setResponseHeader
from girder.api.describe import Description, describeRoute
from girder.constants import AccessType, SortDir
from girder.models.folder import Folder
from girder.models.model_base import ValidationException

from .base import IsicResource
from ..models.annotation import Annotation
from ..models.featureset import Featureset
from ..models.image import Image
from ..models.study import Study
from ..models.user import User


class StudyResource(IsicResource):
    def __init__(self,):
        super(StudyResource, self).__init__()
        self.resourceName = 'study'

        self.route('GET', (), self.find)
        self.route('GET', (':id',), self.getStudy)
        self.route('POST', (), self.createStudy)
        self.route('POST', (':id', 'users'), self.addAnnotators)
        self.route('POST', (':id', 'images'), self.addImages)
        self.route('DELETE', (':id',), self.deleteStudy)
        self.route('DELETE', (':id', 'users', ':userId',), self.deleteAnnotator)

    @describeRoute(
        Description('Return a list of annotation studies.')
        .pagingParams(defaultSort='lowerName')
        .param('detail', 'Display the full information for each image, instead of a summary.',
               required=False, dataType='boolean', default=False)
        .param('state', 'Filter studies to those at a given state', paramType='query',
               required=False, enum=('active', 'complete'))
        .param('userId', 'Filter studies to those containing a user ID, or "me".',
               paramType='query', required=False)
        .errorResponse()
    )
    @access.cookie
    @access.public
    def find(self, params):
        currentUser = self.getCurrentUser()
        detail = self.boolParam('detail', params, default=False)
        limit, offset, sort = self.getPagingParameters(params, 'lowerName')

        annotatorUser = None
        if params.get('userId'):
            if params['userId'] == 'me':
                annotatorUser = currentUser
            else:
                annotatorUser = User().load(params['userId'], force=True, exc=True)

        state = None
        if params.get('state'):
            state = params['state']
            if state not in {Study().State.ACTIVE, Study().State.COMPLETE}:
                raise ValidationException('Value may only be "active" or "complete".', 'state')

        filterFunc = Study().filter if detail else Study().filterSummary
        return [
            filterFunc(study, currentUser)
            for study in
            Study().filterResultsByPermission(
                Study().find(query=None, annotatorUser=annotatorUser, state=state, sort=sort),
                user=currentUser, level=AccessType.READ, limit=limit, offset=offset
            )
        ]

    @describeRoute(
        Description('Get a study by ID.')
        .param('id', 'The ID of the study.', paramType='path')
        .param('format', 'The output format.', paramType='query', required=False,
               enum=('csv', 'json'), default='json')
        .errorResponse()
    )
    @access.cookie
    @access.public
    @loadmodel(model='study', plugin='isic_archive', level=AccessType.READ)
    def getStudy(self, study, params):
        if params.get('format') == 'csv':
            setResponseHeader('Content-Type', 'text/csv')
            setResponseHeader('Content-Disposition',
                              'attachment; filename="%s.csv"' % study['name'])
            return functools.partial(self._getStudyCSVStream, study)

        else:
            user = self.getCurrentUser()
            return Study().filter(study, user)

    def _getStudyCSVStream(self, study):
        currentUser = self.getCurrentUser()

        featureset = Featureset().load(study['meta']['featuresetId'], exc=True)
        csvFields = tuple(itertools.chain(
            ('study_name', 'study_id',
             'user_name', 'user_id',
             'image_name', 'image_id',
             'flag_status', 'elapsed_seconds'),
            (feature['id'] for feature in featureset['globalFeatures']),
            ('superpixel_id',),
            (feature['id'] for feature in featureset['localFeatures'])
        ))

        responseBody = StringIO()
        csvWriter = csv.DictWriter(responseBody, csvFields, restval='')

        csvWriter.writeheader()
        yield responseBody.getvalue()
        responseBody.seek(0)
        responseBody.truncate()

        images = list(
            Study().getImages(study).sort('lowerName', SortDir.ASCENDING))

        for annotatorUser, image in itertools.product(
            sorted(
                Study().getAnnotators(study),
                key=lambda annotatorUser: User().obfuscatedName(annotatorUser)),
            images
        ):
            # this will iterate either 0 or 1 times
            for annotation in Study().childAnnotations(
                study=study,
                annotatorUser=annotatorUser,
                image=image,
                state=Study().State.COMPLETE
            ):
                elapsedSeconds = \
                    int((annotation['meta']['stopTime'] -
                         annotation['meta']['startTime']).total_seconds())

                filteredAnnotatorUser = User().filterSummary(annotatorUser, currentUser)
                annotatorUserName = filteredAnnotatorUser['name']
                if 'login' in filteredAnnotatorUser:
                    annotatorUserName += ' [%s %s (%s)]' % (
                        filteredAnnotatorUser['firstName'],
                        filteredAnnotatorUser['lastName'],
                        filteredAnnotatorUser['login'])

                outDictBase = {
                    'study_name': study['name'],
                    'study_id': str(study['_id']),
                    'user_name': annotatorUserName,
                    'user_id': str(annotatorUser['_id']),
                    'image_name': image['name'],
                    'image_id': str(image['_id']),
                    'flag_status': annotation['meta']['status'],
                    'elapsed_seconds': elapsedSeconds
                }

                outDict = outDictBase.copy()
                for globalFeature in featureset['globalFeatures']:
                    if globalFeature['id'] in annotation['meta']['annotations']:
                        outDict[globalFeature['id']] = \
                            annotation['meta']['annotations'][globalFeature['id']]
                csvWriter.writerow(outDict)
                yield responseBody.getvalue()
                responseBody.seek(0)
                responseBody.truncate()

                # TODO: move this into the query
                if 'localFeatures' in annotation['meta']['annotations']:
                    superpixelCount = len(next(six.viewvalues(
                        annotation['meta']['annotations']['localFeatures'])))
                    for superpixelMum in xrange(superpixelCount):

                        outDict = outDictBase.copy()
                        outDict['superpixel_id'] = superpixelMum
                        for featureName, featureValue in six.viewitems(
                                annotation['meta']['annotations']['localFeatures']):
                            outDict[featureName] = featureValue[superpixelMum]

                        csvWriter.writerow(outDict)
                        yield responseBody.getvalue()
                        responseBody.seek(0)
                        responseBody.truncate()

    @describeRoute(
        Description('Create an annotation study.')
        .param('name', 'The name of the study.', paramType='form')
        .param('featuresetId', 'The featureset ID of the study.', paramType='form')
        .param('userIds', 'The annotators user IDs of the study, as a JSON array.',
               paramType='form')
        .param('imageIds', 'The image IDs of the study, as a JSON array.', paramType='form')
        .errorResponse('Write access was denied on the parent folder.', 403)
    )
    @access.user
    def createStudy(self, params):
        creatorUser = self.getCurrentUser()
        User().requireAdminStudy(creatorUser)

        params = self._decodeParams(params)
        self.requireParams(['name', 'featuresetId', 'userIds', 'imageIds'], params)

        studyName = params['name'].strip()
        if not studyName:
            raise ValidationException('Name must not be empty.', 'name')

        featuresetId = params['featuresetId']
        if not featuresetId:
            raise ValidationException('Invalid featureset ID.', 'featuresetId')
        featureset = Featureset().load(featuresetId, exc=True)

        if len(set(params['userIds'])) != len(params['userIds']):
            raise ValidationException('Duplicate user IDs.', 'userIds')
        annotatorUsers = [
            User().load(annotatorUserId, user=creatorUser, level=AccessType.READ, exc=True)
            for annotatorUserId in params['userIds']
        ]

        if len(set(params['imageIds'])) != len(params['imageIds']):
            raise ValidationException('Duplicate image IDs.', 'imageIds')
        images = [
            # TODO: This should probably not allow images that the user only as access to via an
            # annotation
            Image().load(imageId, user=creatorUser, level=AccessType.READ, exc=True)
            for imageId in params['imageIds']
        ]

        study = Study().createStudy(
            name=studyName,
            creatorUser=creatorUser,
            featureset=featureset,
            annotatorUsers=annotatorUsers,
            images=images)

        return self.getStudy(id=study['_id'], params={})

    @describeRoute(
        Description('Add annotator users to a study.')
        .param('id', 'The ID of the study.', paramType='path')
        .param('userIds', 'The user IDs to add, as a JSON array.', paramType='form')
        .errorResponse('ID was invalid.')
        .errorResponse('You don\'t have permission to add a study annotator.', 403)
    )
    @access.user
    @loadmodel(model='study', plugin='isic_archive', level=AccessType.READ)
    def addAnnotators(self, study, params):
        # TODO: make the loadmodel decorator use AccessType.WRITE,
        # once permissions work
        params = self._decodeParams(params)
        self.requireParams(['userIds'], params)

        creatorUser = self.getCurrentUser()
        User().requireAdminStudy(creatorUser)

        # Load all users before adding any, to ensure all are valid
        if len(set(params['userIds'])) != len(params['userIds']):
            raise ValidationException('Duplicate user IDs.', 'userIds')
        annotatorUsers = [
            User().load(userId, user=creatorUser, level=AccessType.READ, exc=True)
            for userId in params['userIds']
        ]
        # Existing duplicate Annotators are tricky to check for, because it's
        # possible to have a Study with multiple annotator Users (each with a
        # sub-Folder), but with no Images yet, and thus no Annotation (Items)
        # inside yet
        duplicateAnnotatorFolders = Folder().find({
            'parentId': study['_id'],
            'meta.userId': {'$in': [annotatorUser['_id'] for annotatorUser in annotatorUsers]}
        })
        if duplicateAnnotatorFolders.count():
            # Just list the first duplicate
            duplicateAnnotatorFolder = next(iter(duplicateAnnotatorFolders))
            raise ValidationException('Annotator user "%s" is already part of the study.' %
                                      duplicateAnnotatorFolder['meta']['userId'])
        # Look up images only once for efficiency
        images = Study().getImages(study)
        for annotatorUser in annotatorUsers:
            Study().addAnnotator(study, annotatorUser, creatorUser, images)

        return self.getStudy(id=study['_id'], params={})

    @describeRoute(
        Description('Add images to a study.')
        .param('id', 'The ID of the study.', paramType='path')
        .param('imageIds', 'The image IDs to add, as a JSON array.', paramType='form')
        .errorResponse('ID was invalid.')
        .errorResponse('You don\'t have permission to add a study image.', 403)
    )
    @access.user
    @loadmodel(model='study', plugin='isic_archive', level=AccessType.READ)
    def addImages(self, study, params):
        params = self._decodeParams(params)
        self.requireParams(['imageIds'], params)

        creatorUser = self.getCurrentUser()
        User().requireAdminStudy(creatorUser)

        # Load all images before adding any, to ensure all are valid and
        # accessible
        if len(set(params['imageIds'])) != len(params['imageIds']):
            raise ValidationException('Duplicate image IDs.', 'imageIds')
        images = [
            # TODO: This should probably not allow images that the user only as access to via an
            # annotation
            Image().load(imageId, user=creatorUser, level=AccessType.READ, exc=True)
            for imageId in params['imageIds']
        ]
        duplicateAnnotations = Annotation().find({
            'meta.studyId': study['_id'],
            'meta.imageId': {'$in': [image['_id'] for image in images]}
        })
        if duplicateAnnotations.count():
            # Just list the first duplicate
            duplicateAnnotation = next(iter(duplicateAnnotations))
            raise ValidationException(
                'Image "%s" is already part of the study.' % duplicateAnnotation['meta']['imageId'])
        for image in images:
            Study().addImage(study, image, creatorUser)

        return self.getStudy(id=study['_id'], params={})

    @describeRoute(
        Description('Delete a study.')
        .param('id', 'The ID of the study.', paramType='path')
        .errorResponse('ID was invalid.')
    )
    @access.user
    @loadmodel(model='study', plugin='isic_archive', level=AccessType.READ)
    def deleteStudy(self, study, params):
        user = self.getCurrentUser()
        # For now, study admins will be the ones that can delete studies
        User().requireAdminStudy(user)

        if Study().childAnnotations(study=study, state=Study().State.COMPLETE).count():
            raise RestException('Study has completed annotations.', 409)

        Study().remove(study)

        # No Content
        cherrypy.response.status = 204

    @describeRoute(
        Description('Delete an annotator from a study.')
        .param('id', 'The ID of the study.', paramType='path')
        .param('userId', 'The ID of the annotator.', paramType='path')
        .errorResponse('ID was invalid.')
    )
    @access.user
    @loadmodel(model='study', plugin='isic_archive', level=AccessType.READ)
    @loadmodel(model='user', plugin='isic_archive', map={'userId': 'annotatorUser'},
               level=AccessType.READ)
    def deleteAnnotator(self, study, annotatorUser, params):
        user = self.getCurrentUser()
        # For now, study admins will be the ones that can delete annotators
        User().requireAdminStudy(user)

        if Study().childAnnotations(
                study=study, annotatorUser=annotatorUser, state=Study().State.COMPLETE).count():
            raise RestException('Annotator user has completed annotations.', 409)

        try:
            Study().removeAnnotator(study, annotatorUser)
        except ValidationException as e:
            raise ValidationException(str(e), 'userId')

        # No Content
        cherrypy.response.status = 204
