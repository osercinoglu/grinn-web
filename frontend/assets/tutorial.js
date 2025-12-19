/**
 * gRINN Web Tutorial System
 * Uses driver.js for guided tours with interactive action-based progression
 * Tutorial configurations are loaded from JSON files based on current page
 */

// Map URL paths to tutorial config files
const TUTORIAL_CONFIG_MAP = {
    '/': '/assets/tutorial-main.json',
    '/queue': '/assets/tutorial-queue.json',
    '/monitor': '/assets/tutorial-monitor.json',  // Pattern for /monitor/* pages
    '/help': null  // No tutorial for help page (it IS the help)
};

// Store active driver instance for proper cleanup
let activeDriver = null;

// Global flag to indicate tutorial is active (used to skip modals)
window.grinnTutorialActive = false;

// Store observers for cleanup
let activeObservers = {
    mutation: null,
    click: null,
    element: null
};

/**
 * Clean up any active observers
 */
function cleanupObservers() {
    if (activeObservers.mutation) {
        activeObservers.mutation.disconnect();
        activeObservers.mutation = null;
    }
    if (activeObservers.click && activeObservers.element) {
        activeObservers.element.removeEventListener('click', activeObservers.click);
        activeObservers.click = null;
        activeObservers.element = null;
    }
}

/**
 * Wait for a click on a specific element (polls for element existence)
 * @param {string} selector - CSS selector for the element to watch
 * @returns {Promise} Resolves when the element is clicked
 */
function observeClick(selector) {
    return new Promise((resolve) => {
        // Poll for element existence (handles modals that render asynchronously)
        const waitForElement = setInterval(() => {
            const el = document.querySelector(selector);
            if (el && el.offsetParent !== null) {
                clearInterval(waitForElement);
                
                const handler = () => {
                    console.log(`[Tutorial] Click detected on ${selector}`);
                    el.removeEventListener('click', handler);
                    resolve();
                };
                
                activeObservers.element = el;
                activeObservers.click = handler;
                el.addEventListener('click', handler);
            }
        }, 100);
        
        // Store interval for cleanup
        activeObservers.mutation = { disconnect: () => clearInterval(waitForElement) };
        
        // Timeout after 30 seconds
        setTimeout(() => {
            clearInterval(waitForElement);
            console.warn(`[Tutorial] Timeout waiting for element: ${selector}`);
        }, 30000);
    });
}

/**
 * Wait for a click on target element OR detect cancellation (modal close, cancel button)
 * @param {string} selector - CSS selector for the target element to watch
 * @param {string} cancelSelector - CSS selector(s) for cancel elements (comma-separated)
 * @returns {Promise} Resolves with {clicked: true} or {cancelled: true}
 */
function observeClickOrCancel(selector, cancelSelector) {
    return new Promise((resolve) => {
        let resolved = false;
        const cleanup = () => {
            resolved = true;
            if (activeObservers.mutation) {
                activeObservers.mutation.disconnect();
                activeObservers.mutation = null;
            }
        };
        
        // Poll for target element and attach click handler
        const waitForElement = setInterval(() => {
            if (resolved) {
                clearInterval(waitForElement);
                return;
            }
            
            const el = document.querySelector(selector);
            if (el && el.offsetParent !== null) {
                clearInterval(waitForElement);
                
                const handler = () => {
                    if (resolved) return;
                    console.log(`[Tutorial] Click detected on ${selector}`);
                    el.removeEventListener('click', handler);
                    cleanup();
                    resolve({ clicked: true });
                };
                
                activeObservers.element = el;
                activeObservers.click = handler;
                el.addEventListener('click', handler);
            }
        }, 100);
        
        // Watch for cancel actions
        if (cancelSelector) {
            const cancelSelectors = cancelSelector.split(',').map(s => s.trim());
            
            // Attach click handlers to cancel elements
            cancelSelectors.forEach(cs => {
                const checkCancel = setInterval(() => {
                    if (resolved) {
                        clearInterval(checkCancel);
                        return;
                    }
                    const cancelEl = document.querySelector(cs);
                    if (cancelEl) {
                        clearInterval(checkCancel);
                        const cancelHandler = () => {
                            if (resolved) return;
                            console.log(`[Tutorial] Cancel detected on ${cs}`);
                            cancelEl.removeEventListener('click', cancelHandler);
                            cleanup();
                            clearInterval(waitForElement);
                            resolve({ cancelled: true });
                        };
                        cancelEl.addEventListener('click', cancelHandler);
                    }
                }, 100);
            });
            
            // Also watch for modal backdrop clicks (modal closing)
            const modalObserver = setInterval(() => {
                if (resolved) {
                    clearInterval(modalObserver);
                    return;
                }
                // Check if the target element disappeared (modal closed)
                const el = document.querySelector(selector);
                const modal = document.querySelector('.modal.show');
                if (!el && !modal && activeObservers.element) {
                    console.log('[Tutorial] Modal closed - cancelling');
                    cleanup();
                    clearInterval(waitForElement);
                    clearInterval(modalObserver);
                    resolve({ cancelled: true });
                }
            }, 200);
        }
        
        // Store for cleanup
        activeObservers.mutation = { disconnect: () => clearInterval(waitForElement) };
        
        // Timeout after 60 seconds
        setTimeout(() => {
            if (!resolved) {
                cleanup();
                clearInterval(waitForElement);
                console.warn(`[Tutorial] Timeout waiting for action`);
                resolve({ cancelled: true });
            }
        }, 60000);
    });
}

/**
 * Wait for an element to have children (content loaded)
 * @param {string} selector - CSS selector for the container element
 * @returns {Promise} Resolves when the element has children
 */
function observeChildren(selector) {
    return new Promise((resolve) => {
        const el = document.querySelector(selector);
        if (!el) {
            console.warn(`[Tutorial] observeChildren: Element not found: ${selector}`);
            resolve();
            return;
        }
        
        // Already has children?
        if (el.children.length > 0) {
            console.log(`[Tutorial] Element ${selector} already has children`);
            resolve();
            return;
        }
        
        // Watch for children being added
        const observer = new MutationObserver((mutations, obs) => {
            if (el.children.length > 0) {
                console.log(`[Tutorial] Children detected in ${selector}`);
                obs.disconnect();
                resolve();
            }
        });
        
        activeObservers.mutation = observer;
        observer.observe(el, { childList: true, subtree: true });
    });
}

/**
 * Wait for an element to become visible (display not none, opacity > 0)
 * @param {string} selector - CSS selector for the element
 * @returns {Promise} Resolves when the element is visible
 */
function observeVisibility(selector) {
    return new Promise((resolve) => {
        const checkVisibility = () => {
            const el = document.querySelector(selector);
            if (!el) return false;
            
            const style = window.getComputedStyle(el);
            const isVisible = style.display !== 'none' && 
                              style.visibility !== 'hidden' && 
                              style.opacity !== '0' &&
                              el.offsetParent !== null;
            return isVisible;
        };
        
        // Already visible?
        if (checkVisibility()) {
            console.log(`[Tutorial] Element ${selector} is already visible`);
            resolve();
            return;
        }
        
        // Poll for visibility changes (more reliable than MutationObserver for style changes)
        const interval = setInterval(() => {
            if (checkVisibility()) {
                console.log(`[Tutorial] Element ${selector} became visible`);
                clearInterval(interval);
                resolve();
            }
        }, 200);
        
        // Store for cleanup
        activeObservers.mutation = { disconnect: () => clearInterval(interval) };
    });
}

/**
 * Process waitForAction configuration and return a promise
 * @param {Object} action - The waitForAction configuration
 * @returns {Promise} Resolves when the action is completed (or with {cancelled: true} for clickOrCancel)
 */
function waitForAction(action) {
    if (!action) return Promise.resolve();
    
    switch (action.type) {
        case 'click':
            return observeClick(action.selector);
        case 'clickOrCancel':
            return observeClickOrCancel(action.selector, action.cancelSelector);
        case 'children':
            return observeChildren(action.selector);
        case 'visible':
            return observeVisibility(action.selector);
        default:
            console.warn(`[Tutorial] Unknown action type: ${action.type}`);
            return Promise.resolve();
    }
}

/**
 * Get the appropriate tutorial config file path based on current URL
 */
function getTutorialConfigPath() {
    const pathname = window.location.pathname;
    
    // Exact match first
    if (TUTORIAL_CONFIG_MAP[pathname]) {
        return TUTORIAL_CONFIG_MAP[pathname];
    }
    
    // Pattern match for /monitor/{job_id} or /job/{job_id}
    if (pathname.startsWith('/monitor/') || pathname.startsWith('/job/')) {
        return TUTORIAL_CONFIG_MAP['/monitor'];
    }
    
    // Default to main page tutorial
    return TUTORIAL_CONFIG_MAP['/'];
}

/**
 * Filter tutorial steps to only include elements that exist on the page
 */
function filterValidSteps(steps) {
    return steps.filter(step => {
        if (!step.element) return true;  // Steps without element (e.g., modals) are always valid
        const el = document.querySelector(step.element);
        if (!el) {
            console.log(`[Tutorial] Skipping step - element not found: ${step.element}`);
            return false;
        }
        return true;
    });
}

/**
 * Clean up any active tutorial
 */
function cleanupTutorial() {
    cleanupObservers();
    if (activeDriver) {
        try {
            activeDriver.destroy();
            console.log('[Tutorial] Cleaned up active driver instance');
        } catch (e) {
            console.log('[Tutorial] Driver cleanup error (may already be destroyed):', e);
        }
        activeDriver = null;
    }
}

/**
 * Start the tutorial for the current page
 */
async function startTutorial() {
    // Clean up any existing tutorial first
    cleanupTutorial();
    
    // Check if driver.js is loaded
    if (typeof window.driver === 'undefined') {
        console.error('[Tutorial] driver.js is not loaded');
        alert('Tutorial system is not available. Please refresh the page and try again.');
        return;
    }
    
    const configPath = getTutorialConfigPath();
    
    if (!configPath) {
        console.log('[Tutorial] No tutorial available for this page');
        alert('No tutorial is available for this page.');
        return;
    }
    
    try {
        // Fetch tutorial configuration
        const response = await fetch(configPath);
        if (!response.ok) {
            throw new Error(`Failed to load tutorial config: ${response.status}`);
        }
        
        const config = await response.json();
        console.log(`[Tutorial] Loaded config from ${configPath}:`, config);
        
        // Filter to only valid steps
        const validSteps = filterValidSteps(config.steps || []);
        
        if (validSteps.length === 0) {
            console.warn('[Tutorial] No valid steps found for current page');
            alert('Tutorial steps are not available for this page state. Please ensure the page is fully loaded.');
            return;
        }
        
        // Create driver instance with gRINN-themed styling
        activeDriver = window.driver.js.driver({
            showProgress: true,
            showButtons: ['next', 'previous', 'close'],
            steps: validSteps,
            animate: true,
            allowClose: true,
            allowKeyboardControl: false,  // Disable keyboard nav to enforce action requirements
            overlayClickNext: false,
            stagePadding: 10,
            stageRadius: 8,
            popoverClass: 'grinn-tutorial-popover',
            progressText: '{{current}} of {{total}}',
            nextBtnText: 'Next →',
            prevBtnText: '← Back',
            doneBtnText: 'Done ✓',
            
            // Block forward navigation for action-required steps
            onNextClick: (element, step, opts) => {
                const stepIndex = activeDriver.getActiveIndex();
                const stepConfig = validSteps[stepIndex];
                
                if (stepConfig && stepConfig.waitForAction) {
                    // Block advancement - action observer will call moveNext() when action is performed
                    console.log(`[Tutorial] Blocking next - step ${stepIndex} requires action`);
                    return;
                }
                
                // Normal step - allow advancement
                activeDriver.moveNext();
            },
            
            // Use onPopoverRender for DOM manipulation (popover DOM is guaranteed to exist)
            onPopoverRender: (popover, { config, state }) => {
                const stepIndex = activeDriver.getActiveIndex();
                const stepConfig = validSteps[stepIndex];
                
                // Clean up previous observers when popover renders
                cleanupObservers();
                
                if (stepConfig && stepConfig.waitForAction) {
                    console.log(`[Tutorial] Step ${stepIndex} requires action:`, stepConfig.waitForAction);
                    
                    // Hide the next button using driver.js-provided reference
                    if (popover.nextButton) {
                        popover.nextButton.style.display = 'none';
                    }
                    
                    // Add waiting indicator to the footer
                    if (popover.footer && !document.querySelector('.tutorial-waiting-indicator')) {
                        const waitingIndicator = document.createElement('span');
                        waitingIndicator.className = 'tutorial-waiting-indicator';
                        waitingIndicator.innerHTML = '<i class="fas fa-hand-pointer" style="margin-right: 5px;"></i>Perform the action to continue...';
                        waitingIndicator.style.cssText = 'color: #5A7A60; font-size: 0.85rem; font-style: italic; display: flex; align-items: center;';
                        popover.footer.insertBefore(waitingIndicator, popover.footer.firstChild);
                    }
                    
                    // Set up the action observer
                    waitForAction(stepConfig.waitForAction).then((result) => {
                        // Check if action was cancelled (modal closed, cancel button clicked)
                        if (result && result.cancelled) {
                            console.log(`[Tutorial] Action cancelled for step ${stepIndex} - ending tutorial`);
                            if (activeDriver) {
                                activeDriver.destroy();
                            }
                            return;
                        }
                        
                        console.log(`[Tutorial] Action completed for step ${stepIndex}`);
                        
                        // Remove waiting indicator
                        const waitingIndicator = document.querySelector('.tutorial-waiting-indicator');
                        if (waitingIndicator) {
                            waitingIndicator.remove();
                        }
                        
                        // Small delay then auto-advance to next step
                        setTimeout(() => {
                            if (activeDriver) {
                                activeDriver.moveNext();
                            }
                        }, 300);
                    });
                }
            },
            
            onDestroyed: () => {
                console.log('[Tutorial] Tour completed or closed - cleaning up');
                cleanupObservers();
                activeDriver = null;
                window.grinnTutorialActive = false;
            }
        });
        
        // Set global flag for tutorial mode
        window.grinnTutorialActive = true;
        
        // Start the tour
        activeDriver.drive();
        
    } catch (error) {
        console.error('[Tutorial] Error starting tutorial:', error);
        alert('Failed to load tutorial. Please try again later.');
    }
}

// Expose function globally for Dash clientside callback
window.grinnTutorial = {
    start: startTutorial
};

// Also expose for direct console access during debugging
window.startTutorial = startTutorial;

console.log('[Tutorial] gRINN Tutorial system loaded');
