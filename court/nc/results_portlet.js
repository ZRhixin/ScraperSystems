/**/
window.odyPortal = window.odyPortal || {};

window.odyPortal.SmartSearchResults = function () {
};

window.odyPortal.SmartSearchResults.prototype = function () {
  var me = null;
  var tab = null;
  var tabLink = null;
  var ClearTabUrl = null;
  var PartyDataBaseUrl = null;
  var WarrantGridResultUrl = null;
  var CaseGridResultUrl = null;
  var JudgmentGridResultUrl = null;
  var ProtectionGridResultUrl = null;
  var caseTemplate = null;
  var warrantTemplate = null;
  var judgmentTemplate = null;
  var protectionOrderTemplate = null;
  var refreshTimer;

  var init = function (clearTabUrl, url, warrantResultGridLoadUrl, caseResultGridLoadUrl, judgmentResultGridLoadUrl, protectionResultGridLoadUrl) {
    ClearTabUrl = clearTabUrl;
    PartyDataBaseUrl = url;
    WarrantGridResultUrl = warrantResultGridLoadUrl;
    CaseGridResultUrl = caseResultGridLoadUrl;
    JudgmentGridResultUrl = judgmentResultGridLoadUrl;
    ProtectionGridResultUrl = protectionResultGridLoadUrl;

    var newDiv = odyPortal.utils.newDiv;
    var $smartSearchResults = $('#SmartSearchResults');
    var $html = $('html');


    // Add this so that we can scope CSS selectors specifically to this page
    $html.addClass('portal-smart-search-results');

    tab = TabControl.GetTab($("#SmartSearch3rdTab"));
    tabLink = tab.find("a");

    this.caseTemplate = kendo.template($("#CaseGridTemplate").html());
    this.warrantTemplate = kendo.template($("#WarrantGridTemplate").html());
    this.judgmentTemplate = kendo.template($("#JudgmentGridTemplate").html());
    this.protectionOrderTemplate = kendo.template($("#ProtectionOrderGridTemplate").html());
    this.showPartyCardDetails = showPartyCardDetails;

    TabControl.TabRenderComplete($smartSearchResults, true);

    /**
     * Handles updating the "charges" section of the party cards
     */
    $smartSearchResults.on('tt-charges-requested', handleChargesRequested);
    $smartSearchResults.on('tt-charges-added', handleChargesAdded);

    return;

    function handleChargesRequested() {
      // decrease flickering while layout is worked out
      $('.kendo-party-card-grid-container').addClass('owa-invisible');
    }

    function handleChargesAdded() {
      var $caseCards = $('.case-card');
      $caseCards.each(updateCaseCardCharges);
      setTimeout(function () {
        $('.kendo-party-card-grid-container').removeClass('owa-invisible');
      }, 500);

      function updateCaseCardCharges(i, card) {
        var $card = $(card);
        var caseid = $card.data('caseid');
        var $disp = $('#disposition-' + caseid);
        var dispText = $disp.text().trim();
        if (dispText.length > 0) {

          var $details = $card.find('.details');
          $details.empty();
          $details.append(newDiv('details-heading').text('Charges'));
          $details.append($disp.html());
        }
      }
    }
  };


  /** @namespace odyPortal.smartSearchResultsObj */
  function showPartyCardDetails(dataType, partyID) {
    var gridParent = $("#gridContainer_" + partyID);
    var grid = gridParent.find("[id*='" + dataType + "Container']");

    if (grid.length === 0) {
      gridParent.hide();
      gridParent.html(odyPortal.smartSearchResultsObj[dataType + 'Template']({'PartyId': partyID}));

      gridParent.show();

      $(window).trigger('recheck-kgrid-overflow');
    }

  }

  function gridDataBound() {
    $(".partyDataLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = PartyDataBaseUrl + '?eid=' + element.data("partyId") + '&tabIndex=3';
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();
    });

    setTimeout(updatePartyCardAfterKendo, 1);  // run asynchronously in the next event cycle, giving kendo
                                               // a chance to process first.

    /**
     * This function is to be run after Kendo has completed rendering templates so that it can update
     * the search type indicators (warrant, case, judgment, protection order) to add the count, a link
     * if the presentation logic determines it should be a link, and to potentially apply a class so that
     * the link is auto-clicked if presentation logic determines that type of result should be the first one
     * presented once the page finishes loading.
     */
    function updatePartyCardAfterKendo() {
      $('.party-card-row').each(updateEachPartyCard);

      /**
       * Iteration handler for each party to append the count to the search result types (warrant, case, etc)
       * and update each invidual type to add counter and make it a link if applicable
       *
       * @param {number} i index
       * @param {HTMLElement} e element
       */
      function updateEachPartyCard(i, e) {
        var $e = $(e);                            // make a jQuery wrapper for simpler access
        var count = $e.data('count');             // get the count added in the template by Kendo
        $e.text($e.text() + ' (' + count + ')');  // append the count to the result type indicator

        if (count > 0) {

          var $a = updateResultTypeCounter();     // add link and caseResultsLink where applicable
          $e.empty().append($a);
        }

        /**
         * Updates an individual counter to add a link (if applicable) and class if it is the primary link to
         * be auto-clicked when the party is loaded
         *
         * @return {jQuery} link
         */
        function updateResultTypeCounter() {
          var text = $e.text();                               // get the text content to be potentially wrapped in a link
          var ctype = $e.data('ctype');                       // ctype is the search type for this row (warrant, etc)
          var $pc = $(e).closest('.party-card');              // get a reference to the party card
          var partyId = $pc.data('party-id');                 // gets the encrypted party id for the link
          var searchTypes = $pc.data('search-types').split(); // extract a list of enabled search types
          var $a = $(document.createElement('a'))             // create a link with click handler
            .text(text)
            .on('click', function () {
              showPartyCardDetails(ctype, partyId);
            });

          /*
           * The original presentation logic has the caseResultsLink class applied to a non-case search type
           * if it were the only search type selected for the search
           *
           * Any search result type indicator which has this class will be "auto clicked" to expand the results
           * for that search type once the page finishes loading.
           */

          if (searchTypes.length === 1 && ctype === "case") {
            $a.addClass('caseResultsLink');
          }
          return $a;
        }
      }

      $('.caseResultsLink').click();  // auto-clicks any search type indicator with the class 'caseResultsLink' to
                                      // automatically show results for that type
    }

    //Auto-expand all party results on the grid.
    this.expandRow(this.tbody.find("tr.k-master-row"));
  }

  function gridDetailInit() {
    $(".warrantGridResultLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = WarrantGridResultUrl + '?id=' + element.data("partyId");
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();
    });

    $(".caseGridResultLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = CaseGridResultUrl + '?id=' + element.data("partyId");
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();
    });

    $(".judgmentGridResultLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = JudgmentGridResultUrl + '?id=' + element.data("partyId");
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();
    });

    $(".protectionGridResultLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = ProtectionGridResultUrl + '?id=' + element.data("partyId");
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();
    });
  }

  return {
    init: init,
    gridDataBound: gridDataBound,
    gridDetailInit: gridDetailInit,
    caseTemplate: caseTemplate
  };

}();

var SmartSearchGridResults = function () {
};

SmartSearchGridResults.prototype = function () {
  var me = null;
  var tab = null;
  var tabLink = null;
  var WarrantDataBaseUrl = null;
  var JudgmentDataBaseUrl = null;
  var ProtectionOrderBaseUrl = null;
  var checkedForCharges = false;
  var allCharges = null;
  var lazyLoading = false;
  var busyIndicator = makeBusyIndicatorHtml();

  return {
    init: init,
    casesGridDataBound: casesGridDataBound,
    warrantGridDataBound: warrantGridDataBound,
    judgmentGridDataBound: judgmentGridDataBound,
    protectionOrderGridDataBound: protectionOrderGridDataBound,
    casesGridChange: casesGridChange
  };

  function init(warrantUrl, judgmentUrl, protectionUrl) {
    me = this;
    WarrantDataBaseUrl = warrantUrl;
    JudgmentDataBaseUrl = judgmentUrl;
    ProtectionOrderBaseUrl = protectionUrl;
    tab = TabControl.GetTab($("#SmartSearch3rdTab"));
    tabLink = tab.find("a");

    TabControl.TabRenderComplete($("#SmartSearchResults"), true);
  }

  /* MN Specific Feature turned on in SiteWide Configuration*/

  function warrantGridDataBound() {
    baseGridDataBound('warrant', Array.prototype.slice.call(arguments));
    $(".warrantDataLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = WarrantDataBaseUrl + '?eid=' + element.data("warrantId") + '&tabIndex=3';
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();

      /*The TabControl.Widget.tabs("load", 2); line of code caused the
       * case ROA to load multiple times, causing the  audit to show more
       * views than were actually taking place.  This code is needed, for when
       * the 3rd tab is open.  It is not needed, when you click on a link from the
       * results tab.
       *
       * Check to see if the parent portlet-container has the data-tabid attribute set.
       * If it does, then the link is being called from the 3rd tab, and the
       * TabControl.Widget.tabs("load", 2); code needs to run to open up the case ROA.*/

      var index = null;
      if (element !== undefined) {
        index = element.parents(".portlet-container").data("tabid");
        if (index !== undefined) {
          TabControl.Widget.tabs("load", 2);
        }
      }
    });
  }

  function casesGridChange() {
    $(window).trigger('recheck-kgrid-overflow');
  }

  function casesGridDataBound() {
    baseGridDataBound('case', Array.prototype.slice.call(arguments));
    var busyIndicatorRemoved = true;


    /*  MN Specific feature.
     *  Adds the charge information to the cases.
     */
    // Get the charges for each case in the search results from Portal,
    // if the feature is turned on.  Check to see if the lazy load is already in
    // progress, to prevent this code from running multiple times.

    /** @namespace window.odyPortal.smartSearchShowChargesAndDispositions */
    if (!lazyLoading && window.odyPortal.smartSearchShowChargesAndDispositions) {
      lazyLoading = true;
      if (!checkedForCharges) {
        showBusy();
        // Do not want to run this post request multiple times to get the same data
        checkedForCharges = true;
        /** @namespace window.odyPortal.smartSearchResultCaseIDs */
        /** @namespace window.odyPortal.smartSearchCaseChargesEndpointURL */

        $('#SmartSearchResults').trigger('tt-charges-requested');

        $.post(window.odyPortal.smartSearchCaseChargesEndpointURL, {encryptedCaseIDs: window.odyPortal.smartSearchResultCaseIDs}, function (data) {
          allCharges = data;
          if (allCharges && allCharges.Charges) {
            addChargesToResults(allCharges);
            addIDs();
            removeBusy();
          }
        }).fail(function () {
          removeBusy();
          console.error(arguments);
          toastr.error("Error while loading case charges");
        });
      } else {
        // Do not show the busy indicator if there are no charges.
        // However, show it if the user is paging through a party's cases
        /** @namespace window.lastElementClicked */
        if (allCharges && allCharges.Charges && allCharges.Charges.length > 0 ||
          typeof window.lastElementClicked !== 'undefined') {
          showBusy();
        }
        // Need to wait a second first.  Otherwise the html might not be setup
        // yet.  Will end up searching for a div ID that doesn't exist yet.
        setTimeout(function () {
          if (allCharges && allCharges.Charges) {
            addChargesToResults(allCharges);
            addIDs();

            // For party search results, when paging through the various cases,
            // need to make sure that the vertical position of the page buttons remains consistent
            // after each page renders.  This is a requirement of MN ODY-257069
            if (typeof window.lastElementClicked !== 'undefined') {
              // The page buttons are re rendered after the page is redrawn, so will have to
              // find the new element, from the old element's ID.
              var idOfLastElementClicked = $(window.lastElementClicked).attr('id');
              var lastElement = $('#' + idOfLastElementClicked);
              if (lastElement) {
                try {
                  // Scroll to the element
                  document.getElementById('' + idOfLastElementClicked).scrollIntoView();

                  // Due to the fixed header, the element may not be in view, so will need to adjust the position
                  // based upon the fixed header
                  var headerHeight = 87;
                  // Get the vertical location of the window
                  var scrolledY = window.pageYOffset;
                  // Adjust the scroll position based upon the header height, if we are not at the bottom of the page
                  if (scrolledY && !((window.innerHeight + window.scrollY) >= document.body.offsetHeight)) {
                    window.scroll(0, scrolledY - (window.innerHeight - headerHeight) / 2);

                    // Adjust the scroll position based upon it's previous position in the widnow,
                    // so that the element returns to where it was, when it was originally clicked
                    /** @namespace window.lastElementClickedOffset */
                    if (window.lastElementClickedOffset > 0) {
                      var currentOffest = document.getElementById('' + idOfLastElementClicked).getBoundingClientRect().y;
                      var offsetDifference = lastElementClickedOffset - currentOffest;
                      window.scrollBy(0, -offsetDifference);
                    }
                  }
                } catch (err) {
                  // Catch all for if execution runs through this code path when it shouldn't
                }
              }
            }
            removeBusy();
          }
        }, 1000); // todo fixme race condition
      }
    }
    /* End MN Specific feature*/

    //Auto-expand all case result detail template grids.
    this.expandRow(this.tbody.find("tr.k-master-row"));

    if (usePersonaCaseSummary) {
      SiteHelper.bindCaseLinks();
    } else {
      $(".caseLink").click(function (e) {
        e.preventDefault();
        var element = $(e.currentTarget);
        var url = element.data("url");

        if (url.indexOf("tabIndex") > -1) {
          if (tabLink.attr("href") !== url) {
            tabLink.attr("href", url);
          }

          tab.toggle(true);
          tabLink.click();

          /*The TabControl.Widget.tabs("load", 2); line of code caused the
           * case ROA to load multiple times, causing the  audit to show more
           * views than were actually taking place.  This code is needed, for when
           * the 3rd tab is open.  It is not needed, when you click on a link from the
           * results tab.
           *
           * Check to see if the parent portlet-container has the data-tabid attribute set.
           * If it does, then the link is being called from the 3rd tab, and the
           * TabControl.Widget.tabs("load", 2); code needs to run to open up the case ROA.*/

          var index = null;
          if (element !== undefined) {
            index = element.parents(".portlet-container").data("tabid");
            if (index !== undefined) {
              TabControl.Widget.tabs("load", 2);
            }
          }
        } else {
          window.open(url);
        }
      });
    }


    // When charges are being loaded onto the party or case search results page (MN specific feature), this will
    // obscure the card, and add a busy indicator
    function showBusy() {
      // Check to make sure that this is not called multiple times before it is removed
      if (busyIndicatorRemoved) {
        $('#CasesSection').css('opacity', 0.5);
        $('#PartyResultSection').css('opacity', 0.5);
        $('#BusyIndicator').html(busyIndicator);
      }
      busyIndicatorRemoved = false;
    }

    // Removes the busy indicator created by showBusy()
    function removeBusy() {
      busyIndicatorRemoved = true;
      $('#CasesSection').css('opacity', 1);
      $('#PartyResultSection').css('opacity', 1);
      $('#BusyIndicator').html('');
    }

    // Add ID's to the kendo UI links
    function addIDs() {
      var x = 0;
      $('.cases-container a.k-link').each(function (index, el) {
        var elementID = $(this).attr('id');
        // Only add the ID if it doesn't already exist
        if (elementID == undefined) {
          $(this).attr('id', 'KendoLink' + x);
        }
        // Always increment x so that the numbering will remain consistent.
        // Each time a new kendo page is rendered, the UI is rerendered, and the ID's
        // will need to be regenerated.
        x++;
      });
    }

    /**
     * Adds charges to results
     *
     * @param charges
     * @param charges.Charges
     * @param charges.EncryptedCaseId
     * @param charges.Html
     */
    function addChargesToResults(charges) {
      charges && (charges.Charges || []).forEach(addChargeContent);
      $('#SmartSearchResults').trigger('tt-charges-added');

      function addChargeContent(charge) {
        if (charge) {
          $("#disposition-" + charge.EncryptedCaseId)
            .html('')
            .append(charge.Html);
        }
      }

      lazyLoading = false;
    }

  }

  function judgmentGridDataBound() {
    baseGridDataBound('judgment', Array.prototype.slice.call(arguments));

    $(".judgmentLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = JudgmentDataBaseUrl + '?eid=' + element.data("caseid") + '&eventId=' + element.data("eventid") + '&tabIndex=3';
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();

      /*The TabControl.Widget.tabs("load", 2); line of code caused the
       * case ROA to load multiple times, causing the  audit to show more
       * views than were actually taking place.  This code is needed, for when
       * the 3rd tab is open.  It is not needed, when you click on a link from the
       * results tab.
       *
       * Check to see if the parent portlet-container has the data-tabid attribute set.
       * If it does, then the link is being called from the 3rd tab, and the
       * TabControl.Widget.tabs("load", 2); code needs to run to open up the case ROA.*/

      var index = null;
      if (element !== undefined) {
        index = element.parents(".portlet-container").data("tabid");
        if (index !== undefined) {
          TabControl.Widget.tabs("load", 2);
        }
      }
    });
  }

  function protectionOrderGridDataBound() {
    baseGridDataBound('protection-order', Array.prototype.slice.call(arguments));

    /** @namespace window.usePersonaCaseSummary */
    if (window.usePersonaCaseSummary) {
      setTimeout(SiteHelper.bindCaseLinks, 1);
    }

    $(".protectionOrderLink").click(function (e) {
      e.preventDefault();
      var element = $(e.currentTarget);
      var url = ProtectionOrderBaseUrl + '?eid=' + element.data("protectionorderid") + '&tabIndex=3';
      if (tabLink.attr("href") !== url) {
        tabLink.attr("href", url);
      }

      tab.toggle(true);
      tabLink.click();

      /*The TabControl.Widget.tabs("load", 2); line of code caused the
       * case ROA to load multiple times, causing the  audit to show more
       * views than were actually taking place.  This code is needed, for when
       * the 3rd tab is open.  It is not needed, when you click on a link from the
       * results tab.
       *
       * Check to see if the parent portlet-container has the data-tabid attribute set.
       * If it does, then the link is being called from the 3rd tab, and the
       * TabControl.Widget.tabs("load", 2); code needs to run to open up the case ROA.*/

      var index = null;
      if (element !== undefined) {
        index = element.parents(".portlet-container").data("tabid");
        if (index !== undefined) {
          TabControl.Widget.tabs("load", 2);
        }
      }
    });
  }

  function baseGridDataBound(dataType, args) {
    $(window).trigger('data-bound', dataType, args);
  }

  function makeBusyIndicatorHtml() {
    var newDiv = odyPortal.utils.newDiv;

    return newDiv('tt-busy-indicator')
      .append(
        newDiv('icon')
          .css({
            backgroundColor: '#fcfcfc',
            opacity: 1
          })
          .append(newDiv('rect rect1'))
          .append(newDiv('rect rect2'))
          .append(newDiv('rect rect3'))
      )
      .html();
  }
}();


(function () {
  // This context handles card-morph UI and behavior for kendo grids tagged with class .can-morph-to-card
  var refreshTimer;

  $(window).on('resize', handleGridRefresh);
  $(window).on('recheck-kgrid-overflow', updateKendoGrids);
  $(window).on('data-bound', updateKendoGrids);
  $('.ui-tabs-nav').on('click', updateKendoGrids);

  function updateKendoGrids() {
    handleGridRefresh();
    updateNewCardMorphableKgrids();
  }

  /**
   * Handle extra layout for overflowing kendo grids
   * Call this whenever a significant change is made to the kendo grid DOM
   */
  function handleGridRefresh() {
    var $body = $('body');

    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(handleRefreshThrottled, 100);

    return;

    function handleRefreshThrottled() {
      var isIE = $('html').hasClass('ie');
      var $morphables = $('.can-morph-to-card');

      $body.removeClass('use-card-view'); // remove to check if overflow still exists

      setTimeout(checkAnyOverflow); // allow repaint after .use-card-view is removed

      return;

      function checkAnyOverflow() {
        var isAnyOverflowing = $morphables
          .get()
          .map(isOverflowing)
          .reduce(function (r, e) {
            return r || e;
          }, false);

        if (isAnyOverflowing) {
          $body.addClass('use-card-view');
        }

        return;

        function isOverflowing(element) {
          if (element.scrollWidth > element.clientWidth) {
            var diff = element.scrollWidth - element.clientWidth;
            if (diff > (isIE ? 3 : 0)) {
              return true;
            }
          }
          return false;
        }
      }
    }
  }

  /**
   * Find any new kgrids marked as 'can morph to cards' and prepare them
   */
  function updateNewCardMorphableKgrids() {
    $('.can-morph-to-card')
      .css({
        overflowX: 'auto'
      })
      .not('.is-morph-ready')
      .addClass('is-morph-ready')
      .each(makeKgridCardMorphable);

    $('.k-header-column-menu')
      .removeAttr('tabindex') // normally set to -1 for some reason, which removes keyboard accessibility
      .find('.k-icon.k-i-arrowhead-s')
      .removeClass('k-icon k-i-arrowhead-s')
      .addClass('fa fa-chevron-down') // fixes OWA-1689
      .attr('title', 'Sort / Filter Options');
  }

  function makeKgridCardMorphable(i, kg) {
    var $kg = $(kg);
    var $thead = $(kg).find('thead').first();
    var $kgParent = $kg.parent();

    $thead.addClass('kgrid-card-thead');
    $thead.closest('table').addClass('kgrid-card-table');

    $kgParent.prepend(makeMenuButton());
    $(window).on('click', hideMenu);
    hideMenu();

    // handle when user clicks checkbox to add/removes a column in the kendo menu
    $thead.find('.k-columns-item > ul > li').on('click', function () {
      $(window).trigger('recheck-kgrid-overflow');
    });

    return;

    function makeMenuButton() {
      var icon = odyPortal.utils.newElement('i', 'fa fa-bars');
      var btn = odyPortal.utils.newElement('button', 'icon-button')
        .attr({
          'href': '#',
          'title': 'Sort / Filter Options',
          'type': 'button',
          'value': 'Sort/Filter'
        })
        .append(icon)
        .on('click', handleMenuClick);

      return odyPortal.utils.newDiv('kgrid-thead-menu-button').append(btn);
    }

    function handleMenuClick(event) {
      ($thead.hasClass('is-visible') ? hideMenu : showMenu)();

      event.stopPropagation && event.stopPropagation(); // todo, test in ie
    }

    function showMenu() {
      $thead.addClass('is-visible');
      $kgParent.addClass('card-menu-open');
      $kg.css({minHeight: ($thead.height() + 20) + 'px'}); // expand grid vertically if menu doesn't fit
    }

    function hideMenu() {
      $thead.removeClass('is-visible');
      $kgParent.removeClass('card-menu-open');
      $kg.css({minHeight: 0});
    }

  }

})();
