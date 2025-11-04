frappe.ui.form.on('Opportunity', {
    refresh: function(frm) {
        // Use a more specific selector for the list view within the opportunity form
        // This selector might need to be adjusted based on the actual structure of the form
        var opportunityList = $('.form-grid .grid-body');

        if (opportunityList.length > 0) {
            opportunityList.on('wheel', function(e) {
                // Stop the event from propagating to parent elements
                e.stopPropagation();

                // If the original event's deltaY is not 0, it means it's a vertical scroll
                if (e.originalEvent.deltaY !== 0) {
                    // Prevent the default vertical scroll behavior
                    e.preventDefault();

                    // Add the deltaY to the element's scrollLeft to scroll horizontally
                    this.scrollLeft += e.originalEvent.deltaY;
                }
            });
        }
    }
});
