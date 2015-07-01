#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime

from girder.models.model_base import Model, ValidationException


class Featureset(Model):

    def initialize(self):
        self.name = 'featureset'

    def validate(self, doc):
        # raise ValidationException
        return doc

    def createFeatureset(self, name, version, creator):
        now = datetime.datetime.utcnow()

        return self.save({
            'name': name,
            'creatorId': creator['_id'],
            'created': now,
            'version': version,
            'image_features': [],
            'region_features': [],
        })