isic.views.LayoutFooterView = isic.View.extend({
    initialize: function () {
        this.render();
    },

    render: function () {
        this.$el.html(isic.templates.layoutFooter({
            apiRoot: girder.apiRoot
        }));
        return this;
    }
});
