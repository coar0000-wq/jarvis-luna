/**
 * UAE Sticky Header Script
 * 
 * @package UAEL
 */

(function($) {
    'use strict';

    /**
     * UAE Sticky Header Class
     */
    var UAEStickyHeader = function($element) {
        this.$element = $element;
        this.settings = this.getSettings();
        this.isSticky = false;
        this.lastScrollTop = 0;
        this.scrollDirection = 'up';
        this.ticking = false;
        this.resizeTimer = null;
        
        // Only initialize if sticky is enabled
        if (this.settings.enable === 'yes') {
            this.init();
        }
    };

    UAEStickyHeader.prototype = {
        /**
         * Get element settings
         */
        getSettings: function() {
            // First try to get from the new data attribute
            var stickySettings = this.$element.data('uae-sticky-settings');
            if (stickySettings) {
                // Parse if it's a string
                if (typeof stickySettings === 'string') {
                    try {
                        stickySettings = JSON.parse(stickySettings);
                    } catch (e) {
                        stickySettings = {};
                    }
                }
                return {
                    enable: stickySettings.uae_sticky_header_enable || '',
                    devices: stickySettings.uae_sticky_devices || ['desktop', 'tablet', 'mobile'],
                    scrollDistance: stickySettings.uae_sticky_scroll_distance || { size: 100, unit: 'px' },
                    scrollDistanceTablet: stickySettings.uae_sticky_scroll_distance_tablet || null,
                    scrollDistanceMobile: stickySettings.uae_sticky_scroll_distance_mobile || null,
                    
                    // Visual effects
                    transparentEnable: stickySettings.uae_sticky_transparent_enable || '',
                    transparencyLevel: stickySettings.uae_sticky_transparency_level || { size: 100, unit: '%' },
                    
                    backgroundEnable: stickySettings.uae_sticky_background_enable || '',
                    backgroundType: stickySettings.uae_sticky_background_type || 'solid',
                    backgroundColor: stickySettings.uae_sticky_background_color || '#ffffff',
                    
                    gradientColor1: stickySettings.uae_sticky_gradient_color_1 || '#ffffff',
                    gradientLocation1: stickySettings.uae_sticky_gradient_location_1 || { size: 0, unit: '%' },
                    gradientColor2: stickySettings.uae_sticky_gradient_color_2 || '#f0f0f0',
                    gradientLocation2: stickySettings.uae_sticky_gradient_location_2 || { size: 100, unit: '%' },
                    gradientType: stickySettings.uae_sticky_gradient_type || 'linear',
                    gradientAngle: stickySettings.uae_sticky_gradient_angle || { size: 180, unit: 'deg' },
                    
                    borderEnable: stickySettings.uae_sticky_border_enable || '',
                    borderColor: stickySettings.uae_sticky_border_color || '#e0e0e0',
                    borderThickness: stickySettings.uae_sticky_border_thickness || { size: 1, unit: 'px' },
                    
                    shadowEnable: stickySettings.uae_sticky_shadow_enable || '',
                    shadowColor: stickySettings.uae_sticky_shadow_color || 'rgba(0, 0, 0, 0.1)',
                    shadowVertical: stickySettings.uae_sticky_shadow_vertical || { size: 0, unit: 'px' },
                    shadowBlur: stickySettings.uae_sticky_shadow_blur || { size: 10, unit: 'px' },
                    shadowSpread: stickySettings.uae_sticky_shadow_spread || { size: 0, unit: 'px' },
                    
                    hideOnScrollDown: stickySettings.uae_sticky_hide_on_scroll_down || '',
                    hideThreshold: stickySettings.uae_sticky_hide_threshold || { size: 10, unit: '%' },
                    hideThresholdTablet: stickySettings.uae_sticky_hide_threshold_tablet || null,
                    hideThresholdMobile: stickySettings.uae_sticky_hide_threshold_mobile || null
                };
            }
            
            // Fallback to old method
            var data = this.$element.data('settings') || {};
            return {
                enable: data.uae_sticky_header_enable || '',
                devices: data.uae_sticky_devices || ['desktop', 'tablet', 'mobile'],
                scrollDistance: data.uae_sticky_scroll_distance || { size: 100, unit: 'px' },
                scrollDistanceTablet: data.uae_sticky_scroll_distance_tablet || null,
                scrollDistanceMobile: data.uae_sticky_scroll_distance_mobile || null,
                
                // Visual effects
                transparentEnable: data.uae_sticky_transparent_enable || '',
                transparencyLevel: data.uae_sticky_transparency_level || { size: 100, unit: '%' },
                
                backgroundEnable: data.uae_sticky_background_enable || '',
                backgroundType: data.uae_sticky_background_type || 'solid',
                backgroundColor: data.uae_sticky_background_color || '#ffffff',
              
                gradientColor1: data.uae_sticky_gradient_color_1 || '#ffffff',
                gradientLocation1: data.uae_sticky_gradient_location_1 || { size: 0, unit: '%' },
                gradientColor2: data.uae_sticky_gradient_color_2 || '#f0f0f0',
                gradientLocation2: data.uae_sticky_gradient_location_2 || { size: 100, unit: '%' },
                gradientType: data.uae_sticky_gradient_type || 'linear',
                gradientAngle: data.uae_sticky_gradient_angle || { size: 180, unit: 'deg' },
                
                borderEnable: data.uae_sticky_border_enable || '',
                borderColor: data.uae_sticky_border_color || '#e0e0e0',
                borderThickness: data.uae_sticky_border_thickness || { size: 1, unit: 'px' },
                
                shadowEnable: data.uae_sticky_shadow_enable || '',
                shadowColor: data.uae_sticky_shadow_color || 'rgba(0, 0, 0, 0.1)',
                shadowVertical: data.uae_sticky_shadow_vertical || { size: 0, unit: 'px' },
                shadowBlur: data.uae_sticky_shadow_blur || { size: 10, unit: 'px' },
                shadowSpread: data.uae_sticky_shadow_spread || { size: 0, unit: 'px' },
                
                hideOnScrollDown: data.uae_sticky_hide_on_scroll_down || '',
                hideThreshold: data.uae_sticky_hide_threshold || { size: 10, unit: '%' },
                hideThresholdTablet: data.uae_sticky_hide_threshold_tablet || null,
                hideThresholdMobile: data.uae_sticky_hide_threshold_mobile || null
            };
        },

        /**
         * Initialize sticky header
         */
        init: function() {
            var self = this;
            
            // Check if current device is enabled
            if (!this.isDeviceEnabled()) {
                return;
            }
            
            // Set initial styles
            this.setInitialStyles();
            
            // Bind events
            this.bindEvents();
            
            // Initial check
            this.checkScroll();
        },

        /**
         * Check if sticky is enabled for current device
         */
        isDeviceEnabled: function() {
            var currentDevice = this.getCurrentDevice();
            return this.settings.devices.indexOf(currentDevice) !== -1;
        },

        /**
         * Get current device type
         */
        getCurrentDevice: function() {
            var width = window.innerWidth;
            
            if (width >= 1025) {
                return 'desktop';
            } else if (width >= 768 && width < 1025) {
                return 'tablet';
            } else {
                return 'mobile';
            }
        },

        /**
         * Get scroll distance for current device
         */
        getScrollDistance: function() {
            var device = this.getCurrentDevice();
            var scrollDistance = this.settings.scrollDistance;
            
            if (device === 'tablet' && this.settings.scrollDistanceTablet) {
                scrollDistance = this.settings.scrollDistanceTablet;
            } else if (device === 'mobile' && this.settings.scrollDistanceMobile) {
                scrollDistance = this.settings.scrollDistanceMobile;
            }
            
            // Convert percentage to pixels if needed
            if (scrollDistance.unit === '%') {
                return (window.innerHeight * scrollDistance.size) / 100;
            }
            
            return scrollDistance.size;
        },

        /**
         * Get hide threshold for current device
         */
        getHideThreshold: function() {
            var device = this.getCurrentDevice();
            var hideThreshold = this.settings.hideThreshold;
            
            if (device === 'tablet' && this.settings.hideThresholdTablet) {
                hideThreshold = this.settings.hideThresholdTablet;
            } else if (device === 'mobile' && this.settings.hideThresholdMobile) {
                hideThreshold = this.settings.hideThresholdMobile;
            }
            
            // Convert percentage to pixels if needed
            if (hideThreshold.unit === '%') {
                return (window.innerHeight * hideThreshold.size) / 100;
            }
            
            return hideThreshold.size;
        },

        /**
         * Set initial styles
         */
        setInitialStyles: function() {
            // Add identifier class
            this.$element.addClass('uae-sticky-header-element');
            
            // Store original background color
            var currentBg = this.$element.css('background-color');
            this.$element.data('original-background', currentBg);
            
            // Don't apply transparency here - only when sticky
            
            // Set transition
            this.$element.css({
                'transition': 'all 0.3s ease-in-out'
            });
        },

        /**
         * Apply transparency
         */
        applyTransparency: function () {
            var opacity = (100 - this.settings.transparencyLevel.size) / 100;
            var self = this; // Fix for 'this' context in replace callback
        
            var currentBgColor = this.$element.css('background-color');
            var currentBgImage = this.$element.css('background-image');
            var hasGradient = currentBgImage && currentBgImage !== 'none';
        
            var blurStyles = {
                'backdrop-filter': 'blur(10px)',
                '-webkit-backdrop-filter': 'blur(10px)'
            };
        
            if (hasGradient) {
                // Replace hex colors (3 or 6 digit) in gradient with RGBA having opacity
                var modifiedGradient = currentBgImage.replace(/#([0-9a-f]{3,6})\b/gi, function (hex) {
                    return self.convertHexToRgba(hex, opacity);
                });
                
                // Also replace rgb/rgba colors
                modifiedGradient = modifiedGradient.replace(/rgba?\(([^)]+)\)/gi, function(match, values) {
                    var parts = values.split(',').map(function(v) { return v.trim(); });
                    if (parts.length === 3) {
                        // rgb format - add alpha
                        return 'rgba(' + parts[0] + ', ' + parts[1] + ', ' + parts[2] + ', ' + opacity + ')';
                    } else if (parts.length === 4) {
                        // rgba format - replace alpha
                        return 'rgba(' + parts[0] + ', ' + parts[1] + ', ' + parts[2] + ', ' + opacity + ')';
                    }
                    return match;
                });
        
                this.$element.css($.extend({
                    'background-image': modifiedGradient
                }, blurStyles));
            } else if (
                currentBgColor &&
                currentBgColor !== 'transparent' &&
                currentBgColor !== 'rgba(0, 0, 0, 0)'
            ) {
                // Solid color — convert to rgba
                var rgbaColor = this.convertToRgba(currentBgColor, opacity);
                this.$element.css($.extend({
                    'background-color': rgbaColor
                }, blurStyles));
            } else {
                // No background, apply transparent white
                this.$element.css($.extend({
                    'background-color': 'rgba(255, 255, 255, ' + opacity + ')'
                }, blurStyles));
            }
        },

         /**
         * Convert Hexa color to RGBA with opacity
         */
        convertHexToRgba: function(hex, alpha) {
            hex = hex.replace('#', '');
            if (hex.length === 3) {
                hex = hex.split('').map(char => char + char).join('');
            }
            var bigint = parseInt(hex, 16);
            var r = (bigint >> 16) & 255;
            var g = (bigint >> 8) & 255;
            var b = bigint & 255;
        
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        },
        
        
        /**
         * Convert color to RGBA with opacity
         */
        convertToRgba: function(color, opacity) {
            // If already rgba, update the opacity
            if (color.indexOf('rgba') === 0) {
                return color.replace(/[\d\.]+\)$/g, opacity + ')');
            }
            
            // If rgb, convert to rgba
            if (color.indexOf('rgb') === 0) {
                return color.replace('rgb', 'rgba').replace(')', ', ' + opacity + ')');
            }
            
            // If hex, convert to rgba
            if (color.indexOf('#') === 0) {
                var hex = color.replace('#', '');
                var r = parseInt(hex.substring(0, 2), 16);
                var g = parseInt(hex.substring(2, 4), 16);
                var b = parseInt(hex.substring(4, 6), 16);
                return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + opacity + ')';
            }
            
            // Default fallback
            return 'rgba(255, 255, 255, ' + opacity + ')';
        },

        /**
         * Bind events
         */
        bindEvents: function() {
            var self = this;
            
            // Scroll event with RAF
            $(window).on('scroll.uaeStickyHeader', function() {
                self.requestTick();
            });
            
            // Resize event with debounce
            $(window).on('resize.uaeStickyHeader', function() {
                clearTimeout(self.resizeTimer);
                self.resizeTimer = setTimeout(function() {
                    self.handleResize();
                }, 250);
            });
            
            // Elementor editor events
            if (window.elementorFrontend && window.elementorFrontend.isEditMode()) {
                elementor.channels.editor.on('change', function(model) {
                    if (model.el === self.$element[0]) {
                        self.settings = self.getSettings();
                        self.checkScroll();
                    }
                });
            }
        },

        /**
         * Request animation frame for scroll
         */
        requestTick: function() {
            var self = this;
            
            if (!this.ticking) {
                requestAnimationFrame(function() {
                    self.checkScroll();
                    self.ticking = false;
                });
                this.ticking = true;
            }
        },

        /**
         * Check scroll and apply sticky
         */
        checkScroll: function() {
            var scrollTop = $(window).scrollTop();
            var scrollDistance = this.getScrollDistance();
            
            // Detect scroll direction
            if (scrollTop > this.lastScrollTop) {
                this.scrollDirection = 'down';
            } else {
                this.scrollDirection = 'up';
            }
            this.lastScrollTop = scrollTop;
            
            // Check if should be sticky
            if (scrollTop >= scrollDistance) {
                if (!this.isSticky) {
                    this.makeSticky();
                }
                
                // Handle hide on scroll down
                if (this.settings.hideOnScrollDown === 'yes') {
                    this.handleHideOnScroll();
                }
            } else {
                if (this.isSticky) {
                    this.removeSticky();
                }
            }
        },

        /**
         * Make element sticky
         */
        makeSticky: function() {
            this.isSticky = true;
            this.$element.addClass('uae-sticky--active');
            
            // Apply visual effects
            this.applyVisualEffects();
            
            // Add fixed positioning
            this.$element.css({
                'position': 'fixed',
                'top': '0',
                'left': '0',
                'right': '0',
                'z-index': '9999',
                'width': '100%'
            });
            
            // Add placeholder to prevent layout shift
            this.addPlaceholder();
        },

        /**
         * Remove sticky
         */
        removeSticky: function() {
            this.isSticky = false;
            this.$element.removeClass('uae-sticky--active uae-sticky--hidden');
            
            // Remove visual effects
            this.removeVisualEffects();
            
            // Remove fixed positioning
            this.$element.css({
                'position': '',
                'top': '',
                'left': '',
                'right': '',
                'z-index': '',
                'width': ''
            });
            
            // Remove placeholder
            this.removePlaceholder();
        },

        /**
         * Apply visual effects when sticky
         */
        applyVisualEffects: function() {
            var self = this;
            
            // Background
            if (this.settings.backgroundEnable === 'yes') {
                if (this.settings.backgroundType === 'solid') {
                    // Use jQuery's css method with important flag
                    this.$element.css('background-color', this.settings.backgroundColor);
                    // Also set via native style property for better specificity
                    this.$element[0].style.setProperty('background-color', this.settings.backgroundColor, 'important');
                } else {
                    // Gradient
                    var gradient = this.buildGradient();
                    this.$element.css('background-image', gradient);
                    this.$element[0].style.setProperty('background-image', gradient, 'important');
                    this.$element[0].style.setProperty('background-color', 'transparent', 'important');
                }
            } else if (this.settings.transparentEnable === 'yes') {
                // If no background is set but transparency is enabled, keep it transparent when sticky
                this.applyTransparency();
            }
            
            // Border
            if (this.settings.borderEnable === 'yes') {
                var borderValue = this.settings.borderThickness.size + 'px solid ' + this.settings.borderColor;
                this.$element.css('border-bottom', borderValue);
            }
            
            // Shadow
            if (this.settings.shadowEnable === 'yes') {
                var shadowValue = '0 ' + 
                    this.settings.shadowVertical.size + 'px ' + 
                    this.settings.shadowBlur.size + 'px ' + 
                    this.settings.shadowSpread.size + 'px ' + 
                    this.settings.shadowColor;
                this.$element.css('box-shadow', shadowValue);
            }
        },

        /**
         * Remove visual effects
         */
        removeVisualEffects: function() {
            // Store original background before removing
            var originalBg = this.$element.data('original-background');
            
            this.$element.css({
                'background-color': originalBg || '',
                'background-image': '',
                'border-bottom': '',
                'box-shadow': '',
                'backdrop-filter': '',
                '-webkit-backdrop-filter': '',
                'opacity': '' // Reset opacity for gradient transparency
            });
            
            // Don't reapply transparency here - header should return to original state
        },

        /**
         * Build gradient CSS
         */
        buildGradient: function() {
            var type = this.settings.gradientType;
            var color1 = this.settings.gradientColor1 + ' ' + this.settings.gradientLocation1.size + '%';
            var color2 = this.settings.gradientColor2 + ' ' + this.settings.gradientLocation2.size + '%';
            
            if (type === 'linear') {
                return 'linear-gradient(' + this.settings.gradientAngle.size + 'deg, ' + color1 + ', ' + color2 + ')';
            } else {
                return 'radial-gradient(circle, ' + color1 + ', ' + color2 + ')';
            }
        },

        /**
         * Add placeholder element
         */
        addPlaceholder: function() {
            if (!this.$placeholder) {
                var height = this.$element.outerHeight();
                this.$placeholder = $('<div class="uae-sticky-placeholder"></div>').css({
                    'height': height + 'px',
                    'visibility': 'hidden'
                });
                this.$element.after(this.$placeholder);
            }
        },

        /**
         * Remove placeholder element
         */
        removePlaceholder: function() {
            if (this.$placeholder) {
                this.$placeholder.remove();
                this.$placeholder = null;
            }
        },

        /**
         * Handle hide on scroll down
         */
        handleHideOnScroll: function() {
            var threshold = this.getHideThreshold();
            
            if (this.scrollDirection === 'down' && this.lastScrollTop > threshold) {
                this.$element.addClass('uae-sticky--hidden');
                this.$element.css('transform', 'translateY(-100%)');
            } else if (this.scrollDirection === 'up') {
                this.$element.removeClass('uae-sticky--hidden');
                this.$element.css('transform', 'translateY(0)');
            }
        },

        /**
         * Handle resize
         */
        handleResize: function() {
            // Check if device is still enabled
            if (!this.isDeviceEnabled()) {
                this.removeSticky();
                return;
            }
            
            // Update placeholder height if sticky
            if (this.isSticky && this.$placeholder) {
                this.$placeholder.css('height', this.$element.outerHeight() + 'px');
            }
            
            // Recheck scroll
            this.checkScroll();
        },

        /**
         * Destroy sticky header
         */
        destroy: function() {
            $(window).off('.uaeStickyHeader');
            this.removeSticky();
            this.$element.removeClass('uae-sticky-header-element');
        }
    };

    /**
     * Initialize on ready
     */
    $(window).on('elementor/frontend/init', function() {
        // Handler for sections and containers
        var stickyHandler = function($scope) {
            // Check if it's an HFE header
            if ($scope.closest('.hfe-site-header, .site-header, header').length > 0) {
                new UAEStickyHeader($scope);
            }
        };

        // Register handlers
        elementorFrontend.hooks.addAction('frontend/element_ready/section', stickyHandler);
        elementorFrontend.hooks.addAction('frontend/element_ready/container', stickyHandler);
    });

})(jQuery);