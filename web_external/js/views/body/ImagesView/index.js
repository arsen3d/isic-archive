isic.views.ImagesViewSubViews = isic.views.ImagesViewSubViews || {};

isic.views.ImagesView = isic.View.extend({
    initialize: function () {
        this.model = new isic.views.ImagesViewSubViews.ImagesViewModel();

        // Initialize our subviews
        var params = {
            model: this.model,
            parentView: this
        };
        this.studyPane = new isic.views.ImagesViewSubViews.StudyPane(params);
        this.histogramPane = new isic.views.ImagesViewSubViews.HistogramPane(params);
        this.imageWall = new isic.views.ImagesViewSubViews.ImageWall(params);
        this.pagingPane = new isic.views.ImagesViewSubViews.PagingPane(params);
        this.imageDetailsPane = new isic.views.ImagesViewSubViews.ImageDetailsPane(params);

        $(window).on('resize.ImagesView', _.bind(this.render, this));

        this.listenTo(this.model, 'change:selectedImageId', this.toggleDetailsPane);

        this.render();
    },
    destroy: function () {
        $(window).off('resize.ImagesView');

        isic.View.prototype.destroy.call(this);
    },
    toggleDetailsPane: function () {
        if (this.model.get('selectedImageId') !== null) {
            this.$('#isic-images-imageDetailsPane').css('display', '');
        } else {
            this.$('#isic-images-imageDetailsPane').css('display', 'none');
        }
    },
    render: function () {
        if (!(this.addedTemplate)) {
            this.$el.html(isic.templates.imagesPage({
                staticRoot: girder.staticRoot
            }));
            window.shims.recolorImageFilters(['#00ABFF', '#444499', '#CCCCCC']);
            this.studyPane.setElement(this.$('#isic-images-studyPane'));
            this.histogramPane.setElement(this.$('#isic-images-histogramPane'));
            this.imageWall.setElement(this.$('#isic-images-imageWall'));
            this.pagingPane.setElement(this.$('#isic-images-pagingPane'));
            this.imageDetailsPane.setElement(this.$('#isic-images-imageDetailsPane'));
            this.addedTemplate = true;
        }
        this.imageWall.render();
        this.pagingPane.render();
        this.studyPane.render();
        this.histogramPane.render();
        this.imageDetailsPane.render();

        this.toggleDetailsPane();

        return this;
    }
});

isic.router.route('images', 'images', function (id) {
    girder.events.trigger('g:navigateTo', isic.views.ImagesView);
});
