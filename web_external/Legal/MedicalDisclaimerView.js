isic.views.MedicalDisclaimerView = isic.View.extend({
    initialize: function (settings) {
        this.render();
    },

    render: function () {
        this.$el.html(isic.templates.medicalDisclaimerPage());

        return this;
    }
});

isic.router.route('medicalDisclaimer', 'medicalDisclaimer', function () {
    girder.events.trigger('g:navigateTo', isic.views.MedicalDisclaimerView);
});
