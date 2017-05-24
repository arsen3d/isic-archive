import _ from 'underscore';
import $ from 'jquery';

import events from 'girder/events';
import eventStream from 'girder/utilities/EventStream';
import {getCurrentUser, setCurrentUser} from 'girder/auth';
import UserModel from 'girder/models/UserModel';
import {restRequest} from 'girder/rest';

// Fallback variable for anonymous user with no local storage
let acceptTerms = null;

// Add additional instance methods
UserModel.prototype.name = function () {
    let realName;
    if (this.has('login')) {
        realName = `${this.get('firstName')} ${this.get('lastName')} (${this.get('login')})`;
    }

    let displayName;
    if (this.has('name')) {
        displayName = this.get('name');
        if (realName) {
            displayName += ` [${realName}]`;
        }
    } else {
        // The user should always have either a 'login' or a 'name'
        displayName = realName;
    }
    return displayName;
};

UserModel.prototype.canAcceptTerms = function () {
    return this.get('permissions').acceptTerms === true;
};

UserModel.prototype.setAcceptTerms = function () {
    const deferred = $.Deferred();
    restRequest({
        path: 'user/acceptTerms',
        type: 'POST'
    })
    .done((resp) => {
        if (_.has(resp, 'extra') && resp.extra === 'hasPermission') {
            // Directly update user permissions
            this.get('permissions').acceptTerms = true;
            this.trigger('change:permissions');
            deferred.resolve(resp);
        } else {
            // This should not fail
            deferred.reject(resp);
        }
    })
    .fail((resp) => {
        deferred.reject(resp);
    });
    return deferred.promise();
};

UserModel.prototype.canCreateDataset = function () {
    return this.get('permissions').createDataset;
};

UserModel.prototype.setCanCreateDataset = function () {
    const deferred = $.Deferred();
    restRequest({
        path: 'user/requestCreateDatasetPermission',
        type: 'POST'
    })
    .done((resp) => {
        if (_.has(resp, 'extra') && resp.extra === 'hasPermission') {
            // Directly update user permissions
            this.get('permissions').createDataset = true;
            this.trigger('change:permissions');
            deferred.resolve(resp);
        } else {
            deferred.reject(resp);
        }
    })
    .fail((resp) => {
        deferred.reject(resp);
    });
    return deferred.promise();
};

UserModel.prototype.canReviewDataset = function () {
    return this.get('permissions').reviewDataset;
};

UserModel.prototype.getSegmentationSkill = function () {
    return this.get('permissions').segmentationSkill;
};

UserModel.prototype.canAdminStudy = function () {
    return this.get('permissions').adminStudy;
};

// Patch upstream changePassword to return a promise
// TODO: Remove this once Girder is updated
UserModel.prototype.changePassword = function (oldPassword, newPassword) {
    return restRequest({
        path: `${this.resourceName}/password`,
        data: {
            old: oldPassword,
            new: newPassword
        },
        type: 'PUT',
        error: null
    })
    .done(() => {
        this.trigger('g:passwordChanged');
    })
    .fail((err) => {
        this.trigger('g:error', err);
    });
};

// Add additional static methods
// TODO: Push temporaryTokenLogin to upstream Girder
UserModel.temporaryTokenLogin = function (userId, token) {
    return restRequest({
        path: `user/password/temporary/${userId}`,
        type: 'GET',
        data: {token: token},
        error: null
    })
    .done((resp) => {
        resp.user.token = resp.authToken.token;
        eventStream.close();
        setCurrentUser(new UserModel(resp.user));
        eventStream.open();
        events.trigger('g:login-changed');
    });
};

UserModel.currentUserCanAcceptTerms = function () {
    let currentUser = getCurrentUser();
    if (currentUser) {
        return currentUser.canAcceptTerms();
    } else {
        return (window.localStorage.getItem('acceptTerms') === 'true') ||
               (acceptTerms === true);
    }
};

UserModel.currentUserSetAcceptTerms = function () {
    const currentUser = getCurrentUser();
    if (currentUser) {
        return currentUser.setAcceptTerms();
    } else {
        try {
            window.localStorage.setItem('acceptTerms', 'true');
        } catch (e) {
            acceptTerms = true;
        }
        return $.Deferred().resolve();
    }
};

// Re-export, so all of ISIC can import it from here, and ensure the patched version gets used
export default UserModel;
