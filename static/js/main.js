/**
 * Main JavaScript for Riska's Finance Application
 * Provides common functionality used across multiple pages
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Initialize popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });

    // For all tables with class 'datatable', initialize DataTables
    if (typeof $.fn.DataTable !== 'undefined') {
        $('.datatable').DataTable({
            responsive: true,
            dom: 'Bfrtip',
            buttons: ['csv', 'excel', 'pdf', 'print']
        });
    }

    // Format currency inputs
    document.querySelectorAll('.currency-input').forEach(input => {
        input.addEventListener('blur', function() {
            // Format the number with 2 decimal places
            if (this.value) {
                const value = parseFloat(this.value);
                if (!isNaN(value)) {
                    this.value = value.toFixed(2);
                }
            }
        });
    });

    // Date inputs initialization with today's date if empty
    document.querySelectorAll('.date-input').forEach(input => {
        if (!input.value) {
            const today = new Date();
            const year = today.getFullYear();
            let month = today.getMonth() + 1;
            let day = today.getDate();
            
            month = month < 10 ? '0' + month : month;
            day = day < 10 ? '0' + day : day;
            
            input.value = `${year}-${month}-${day}`;
        }
    });

    // Confirmation dialogs
    document.querySelectorAll('.confirm-action').forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm(this.getAttribute('data-confirm-message') || 'Are you sure you want to perform this action?')) {
                e.preventDefault();
            }
        });
    });

    // Toggle password visibility
    document.querySelectorAll('.toggle-password').forEach(button => {
        button.addEventListener('click', function() {
            const input = document.querySelector(this.getAttribute('data-target'));
            if (input.type === 'password') {
                input.type = 'text';
                this.innerHTML = '<i class="fas fa-eye-slash"></i>';
            } else {
                input.type = 'password';
                this.innerHTML = '<i class="fas fa-eye"></i>';
            }
        });
    });

    // Back button functionality
    document.querySelectorAll('.btn-back').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            window.history.back();
        });
    });

    // Print functionality
    document.querySelectorAll('.btn-print').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            window.print();
        });
    });
});

/**
 * Format a number as currency
 * @param {number} amount - The amount to format
 * @param {string} currencySymbol - Currency symbol to use (default: $)
 * @returns {string} Formatted currency string
 */
function formatCurrency(amount, currencySymbol = '$') {
    return currencySymbol + parseFloat(amount).toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
}

/**
 * Calculate totals for a table with amount inputs
 * @param {string} tableId - ID of the table
 * @param {string} inputName - Name attribute of input fields to total
 * @param {string} totalElementId - ID of element to display total
 */
function calculateTableTotal(tableId, inputName, totalElementId) {
    const inputs = document.querySelectorAll(`#${tableId} input[name="${inputName}"]`);
    let total = 0;
    
    inputs.forEach(input => {
        total += parseFloat(input.value) || 0;
    });
    
    document.getElementById(totalElementId).textContent = formatCurrency(total);
    return total;
}

/**
 * Generate a notification
 * @param {string} message - The message to display
 * @param {string} type - Type of notification (success, error, warning, info)
 * @param {string} elementId - ID of container to display notification (optional)
 */
function showNotification(message, type = 'info', elementId = 'notification') {
    const notificationElement = document.getElementById(elementId);
    if (!notificationElement) return;
    
    notificationElement.innerHTML = message;
    notificationElement.className = `notification ${type}`;
    notificationElement.style.display = 'block';
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        notificationElement.style.display = 'none';
    }, 5000);
}
