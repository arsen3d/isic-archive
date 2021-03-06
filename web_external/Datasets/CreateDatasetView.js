import $ from 'jquery';
import _ from 'underscore';

import FolderModel from 'girder/models/FolderModel';
import UploadWidget from 'girder/views/widgets/UploadWidget';
import {getCurrentUser} from 'girder/auth';

import DatasetModel from '../models/DatasetModel';
import TermsOfUseWidget from '../common/TermsOfUse/TermsOfUseWidget';
import CreateDatasetLicenseInfoWidget from './CreateDatasetLicenseInfoWidget';
import View from '../view';
import {showAlertDialog} from '../common/utilities';
import router from '../router';

import CreateDatasetTemplate from './createDataset.pug';
import './createDataset.styl';
import './uploadWidget.styl';

const CreateDatasetView = View.extend({
    events: {
        'click #isic-upload-reset': function (event) {
            this.resetUpload();
        },
        'click #isic-create-dataset-show-license-info-link': 'showLicenseInfo',
        'change input[name="attribution"]': function (event) {
            // Update attribution name field sensitivity
            let target = $(event.target);
            if (target.val() === 'anonymous') {
                this.$('#isic-dataset-attribution-name').girderEnable(false);
            } else {
                this.$('#isic-dataset-attribution-name').girderEnable(true);
            }
        },
        'change #isic-dataset-license': function (event) {
            // Disable anonymous attribution unless CC-0 license is selected
            let target = $(event.target);
            let anonymous = this.$('#isic-dataset-attribution-anonymous');
            if (target.val() === 'CC-0') {
                anonymous.girderEnable(true);
            } else {
                if (anonymous.prop('checked')) {
                    this.$('#isic-dataset-attribution-attributed-to').prop('checked', true);
                    this.$('#isic-dataset-attribution-attributed-to').change();
                }
                anonymous.girderEnable(false);
            }
        },
        'submit #isic-dataset-form': function (event) {
            event.preventDefault();
            this.$('#isic-dataset-submit').girderEnable(false);

            // Get file ID of uploaded file
            const uploadedFileId = _.isEmpty(this.uploadedFiles)
                ? null
                : this.uploadedFiles[0].id;

            // If no files have been uploaded, delegate error handling to submitDataset()
            this.submitDataset(uploadedFileId);
        }
    },

    initialize: function (settings) {
        this.uploadedFiles = [];
        this.uploadFolder = null;

        this.termsOfUseWidget = new TermsOfUseWidget({
            parentView: this
        });

        this.dataset = new DatasetModel();

        this.listenTo(this.dataset, 'isic:ingestImages:success', () => {
            showAlertDialog({
                text: '<h4>Dataset successfully submitted.</h4>',
                escapedHtml: true,
                callback: () => {
                    // Navigate to register metadata view
                    router.navigate(
                        `dataset/${this.dataset.id}/metadata/register`,
                        {trigger: true});
                }
            });
        });

        this.listenTo(this.dataset, 'isic:ingestImages:error', (resp) => {
            showAlertDialog({
                text: `<h4>Error submitting dataset</h4><br>${_.escape(resp.responseJSON.message)}`,
                escapedHtml: true
            });
            this.$('#isic-dataset-submit').girderEnable(true);
        });

        this.render();
    },

    render: function () {
        this.$el.html(CreateDatasetTemplate());

        if (!this.uploadWidget) {
            this.initializeUploadWidget();
        }
        this.updateUploadWidget();

        this.termsOfUseWidget.setElement(
            this.$('#isic-terms-of-use-container')).render();

        this.$('input#isic-dataset-name').focus();

        return this;
    },

    initializeUploadWidget: function () {
        if (this.uploadWidget) {
            this.stopListening(this.uploadWidget);
            this.uploadWidget.destroy();
        }
        this.uploadWidget = new UploadWidget({
            parentView: this,
            modal: false,
            noParent: true,
            title: false,
            overrideStart: true,
            multiFile: false
        });

        this.uploadWidget.setElement(this.$('.isic-upload-widget-container'));

        this.listenTo(this.uploadWidget, 'g:filesChanged', this.filesSelected);
        this.listenTo(this.uploadWidget, 'g:uploadStarted', this.uploadStarted);
        this.listenTo(this.uploadWidget, 'g:uploadFinished', this.uploadFinished);
    },

    filesSelected: function (files) {
        // TODO: could validate based on file extension
    },
    uploadStarted: function (files) {
        // Prepare upload folder in user's home and start upload
        if (this.uploadFolder) {
            // Folder already created
            this.startUpload(this.uploadFolder);
        } else {
            // Create new upload folder with unique name
            this.uploadFolder = new FolderModel({
                name: `isic_dataset_${Date.now()}`,
                parentType: 'user',
                parentId: getCurrentUser().id,
                description: 'ISIC dataset upload'
            });

            this.uploadFolder
                .once('g:saved', () => {
                    this.startUpload(this.uploadFolder);
                })
                .once('g:error', () => {
                    showAlertDialog({
                        text: 'Could not create upload folder.'
                    });
                })
                .save();
        }
    },

    uploadFinished: function (info) {
        this.uploadedFiles = _.map(
            info.files,
            (file) => ({id: file.id, name: file.name})
        );
        this.updateUploadWidget();
    },

    startUpload: function (folder) {
        // Configure upload widget and begin upload
        this.uploadWidget.parentType = 'folder';
        this.uploadWidget.parent = folder;
        this.uploadWidget.uploadNextFile();
    },

    /**
     * Submit dataset. Delegate all validation to the server.
     * @param [zipFileId] The ID of the .zip file, or null.
     */
    submitDataset: function (zipFileId) {
        let name = this.$('#isic-dataset-name').val();
        let owner = this.$('#isic-dataset-owner').val();
        let description = this.$('#isic-dataset-description').val();
        let license = this.$('#isic-dataset-license').val();
        let signature = this.$('#isic-dataset-agreement-signature').val();
        let anonymous = this.$('#isic-dataset-attribution-anonymous').prop('checked');
        let attribution = this.$('#isic-dataset-attribution-name').val();

        this.dataset.ingestImages(zipFileId, name, owner, description, license,
            signature, anonymous, attribution);
    },

    updateUploadWidget: function () {
        const filesUploaded = !_.isEmpty(this.uploadedFiles);
        this.$('.isic-upload-widget-container').toggle(!filesUploaded);
        this.$('.isic-upload-reset-container').toggle(filesUploaded);

        this.uploadWidget.render();
        this.$('.isic-upload-list').text(`Uploaded: ${_.pluck(this.uploadedFiles, 'name').join(', ')}`);
    },

    resetUpload: function () {
        // Delete uploaded files
        this.uploadFolder
            .once('g:success', () => {
                this.uploadedFiles = [];
                this.updateUploadWidget();
            })
            .removeContents();
    },

    showLicenseInfo: function () {
        if (!this.licenseInfoWidget) {
            this.licenseInfoWidget = new CreateDatasetLicenseInfoWidget({
                el: $('#g-dialog-container'),
                parentView: this
            });
        }
        this.licenseInfoWidget.render();
    }
});

export default CreateDatasetView;
