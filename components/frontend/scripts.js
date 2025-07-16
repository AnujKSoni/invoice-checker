// Tab switching functionality
function switchTab(tabId) {
    // Update navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
    
    // Update tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    document.getElementById(tabId).classList.add('active');
}

// Move Streamlit elements into tabs
function organizeStreamlitElements() {
    setTimeout(() => {
        try {
            // Move file uploader to upload tab
            const fileUploader = document.querySelector('.stFileUploader');
            const selectbox = document.querySelector('.stSelectbox');
            
            if (fileUploader && selectbox) {
                const uploadPlaceholder = document.getElementById('upload-placeholder');
                uploadPlaceholder.appendChild(selectbox.parentElement);
                uploadPlaceholder.appendChild(fileUploader.parentElement);
            }
            
            // Move analysis elements to analyze tab
            const analyzePlaceholder = document.getElementById('analyze-placeholder');
            const elementsToMove = [
                '.stSuccess', '.stColumns', '.stTextArea', '.stSubheader', 
                '.stTextInput', '.stDataFrame', '.stDownloadButton', '.stForm'
            ];
            
            elementsToMove.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(element => {
                    if (!analyzePlaceholder.contains(element) && !element.closest('#upload-placeholder')) {
                        analyzePlaceholder.appendChild(element.parentElement || element);
                    }
                });
            });
            
            // Move sidebar and results to results tab
            const sidebar = document.querySelector('section[data-testid="stSidebar"]');
            const resultsPlaceholder = document.getElementById('results-placeholder');
            
            if (sidebar) {
                resultsPlaceholder.appendChild(sidebar);
            }
            
            // Move compliance results
            const complianceResults = document.querySelectorAll('.metric-card');
            complianceResults.forEach(result => {
                if (!resultsPlaceholder.contains(result)) {
                    resultsPlaceholder.appendChild(result);
                }
            });
            
        } catch (error) {
            console.log('Error organizing elements:', error);
        }
    }, 1000);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    organizeStreamlitElements();
    
    // Re-organize when new elements are added
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length > 0) {
                organizeStreamlitElements();
            }
        });
    });
    
    observer.observe(document.body, { childList: true, subtree: true });
});

// Re-organize on window load as backup
window.addEventListener('load', organizeStreamlitElements);
