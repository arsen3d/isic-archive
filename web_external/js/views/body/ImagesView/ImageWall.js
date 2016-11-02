/*globals d3*/

isic.views.ImagesViewSubViews = isic.views.ImagesViewSubViews || {};

isic.views.ImagesViewSubViews.ImageWall = isic.View.extend({
    initialize: function (settings) {
        this.image = settings.image;
        // For now we'll hard code this (and probably change it in the future),
        // depending on the page size
        this.imageSize = 128;

        this.listenTo(this.model.images, 'g:changed', this.render);
    },
    selectImage: function (imageId) {
        if (imageId !== null) {
            this.image.clear({silent: true});
            this.image.set('_id', imageId);
            this.image.fetch();
        } else {
            this.image.clear();
        }

        var sel = d3.select(this.el)
            .selectAll('img')
            .classed('selected', _.bind(function (d) {
                return d.id === this.image.id;
            }, this));
    },
    render: _.debounce(function () {
        // Ordinarily, we would use the exit selection to clean up after
        // ourselves, but deleting all the img elements has the effect of
        // visually "streaming in" the new data, rather than updating the old
        // images, which feels error-prone.
        d3.select(this.el)
          .selectAll('img')
          .remove();

        d3.select(this.el)
            .selectAll('img')
            .data(this.model.images.map(function (image) {
                return {
                    id: image.id,
                    name: image.get('name')
                };
            }))
            .enter()
            .append('img')
            .classed('thumb', true)
            .attr('src', _.bind(function (d) {
                return girder.apiRoot + '/image/' + d.id + '/thumbnail?width=' + this.imageSize;
            }, this))
            .attr('height', this.imageSize * 0.75)
            .attr('width', this.imageSize)
            .attr('data-toggle', 'tooltip')
            .attr('data-placement', 'auto')
            .attr('data-viewport', '#isic-images-imageWall')
            .on('click', _.bind(function (d) {
                this.clearTooltips();
                if (d3.event.shiftKey) {
                    new isic.views.ImageFullscreenWidget({ // eslint-disable-line no-new
                        el: $('#g-dialog-container'),
                        model: this.model.images.findWhere({_id: d.id}),
                        parentView: this
                    }).render();
                } else {
                    this.selectImage(d.id === this.image.id ? null : d.id);
                }
            }, this))
            .each(function (d) {
                $(this).tooltip({
                    title: d.name
                });
            });
    }, 50),
    clearTooltips: function () {
        $('[data-toggle="tooltip"]').tooltip('hide');
    }
});
