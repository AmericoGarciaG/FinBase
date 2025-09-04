// FinBase Admin Panel - JavaScript Logic

class AdminPanel {
    constructor() {
        this.apiBaseUrl = '/api/v1';
        this.jobs = new Map();
        this.refreshInterval = null;
        this.isRefreshing = false;
        
        this.initializeElements();
        this.attachEventListeners();
        this.initializeApp();
    }

    initializeElements() {
        // Form elements
        this.jobForm = document.getElementById('jobForm');
        this.apiKeyInput = document.getElementById('apiKey');
        this.tickerInput = document.getElementById('ticker');
        this.providerInput = document.getElementById('provider');
        this.startDateInput = document.getElementById('startDate');
        this.endDateInput = document.getElementById('endDate');
        this.submitBtn = document.getElementById('submitBtn');
        this.statusMessages = document.getElementById('statusMessages');

        // Table elements
        this.jobsTableBody = document.getElementById('jobsTableBody');
        this.jobCountElement = document.getElementById('jobCount');
        this.lastRefreshElement = document.getElementById('lastRefresh');
        this.autoRefreshCheckbox = document.getElementById('autoRefresh');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.clearJobsBtn = document.getElementById('clearJobsBtn');
        this.connectionStatus = document.getElementById('connectionStatus');
        this.connectionText = document.getElementById('connectionText');

        // Modal elements
        this.modal = document.getElementById('jobModal');
        this.modalTitle = document.getElementById('modalTitle');
        this.modalBody = document.getElementById('modalBody');
        this.modalClose = document.getElementById('modalClose');
    }

    attachEventListeners() {
        // Form submission
        this.jobForm.addEventListener('submit', (e) => this.handleJobSubmission(e));
        
        // Table controls
        this.refreshBtn.addEventListener('click', () => this.refreshJobs());
        this.clearJobsBtn.addEventListener('click', () => this.clearCompletedJobs());
        this.autoRefreshCheckbox.addEventListener('change', (e) => this.toggleAutoRefresh(e.target.checked));

        // Modal controls
        this.modalClose.addEventListener('click', () => this.closeModal());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.closeModal();
        });

        // Form validation
        this.startDateInput.addEventListener('change', () => this.validateDateRange());
        this.endDateInput.addEventListener('change', () => this.validateDateRange());
        
        // Ticker input formatting
        this.tickerInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9.-]/g, '');
        });
    }

    async initializeApp() {
        // Set default dates (last 30 days)
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - 30);
        
        this.startDateInput.value = startDate.toISOString().split('T')[0];
        this.endDateInput.value = endDate.toISOString().split('T')[0];

        // Load saved API key if available
        const savedApiKey = localStorage.getItem('finbase_admin_api_key');
        if (savedApiKey) {
            this.apiKeyInput.value = savedApiKey;
        }

        // Check API connection
        await this.checkApiConnection();
        
        // Start initial job refresh
        await this.refreshJobs();
        
        // Start auto-refresh if enabled
        if (this.autoRefreshCheckbox.checked) {
            this.startAutoRefresh();
        }
    }

    async checkApiConnection() {
        try {
            this.updateConnectionStatus('checking', 'Checking API connection...');
            
            const response = await fetch(`${this.apiBaseUrl}/symbols`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            if (response.ok) {
                this.updateConnectionStatus('connected', 'API Connected');
            } else {
                this.updateConnectionStatus('error', 'API Error');
            }
        } catch (error) {
            this.updateConnectionStatus('error', 'API Unavailable');
            console.error('API connection check failed:', error);
        }
    }

    updateConnectionStatus(status, text) {
        this.connectionStatus.className = `indicator-dot ${status}`;
        this.connectionText.textContent = text;
        this.connectionText.className = `connection-${status}`;
    }

    validateDateRange() {
        const startDate = new Date(this.startDateInput.value);
        const endDate = new Date(this.endDateInput.value);
        
        if (startDate && endDate && startDate >= endDate) {
            this.endDateInput.setCustomValidity('End date must be after start date');
        } else {
            this.endDateInput.setCustomValidity('');
        }
    }

    async handleJobSubmission(event) {
        event.preventDefault();
        
        if (!this.validateForm()) {
            return;
        }

        const formData = new FormData(this.jobForm);
        const jobData = {
            ticker: formData.get('ticker').toUpperCase(),
            provider: formData.get('provider'),
            start_date: formData.get('startDate'),
            end_date: formData.get('endDate')
        };

        const apiKey = formData.get('apiKey');
        
        // Save API key for future use
        localStorage.setItem('finbase_admin_api_key', apiKey);

        this.setFormLoading(true);
        this.clearStatusMessages();

        try {
            const response = await fetch(`${this.apiBaseUrl}/backfill/jobs`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': apiKey
                },
                body: JSON.stringify(jobData)
            });

            const responseData = await response.json();

            if (response.ok) {
                this.showStatusMessage('success', `Job created successfully! Job ID: ${responseData.job_id}`);
                this.jobForm.reset();
                this.initializeApp(); // Reset form to defaults
                await this.refreshJobs(); // Refresh table immediately
            } else {
                const errorMessage = responseData.detail || responseData.message || 'Failed to create job';
                this.showStatusMessage('error', `Error: ${errorMessage}`);
            }
        } catch (error) {
            console.error('Job submission error:', error);
            this.showStatusMessage('error', 'Network error: Unable to connect to API service');
        } finally {
            this.setFormLoading(false);
        }
    }

    validateForm() {
        let isValid = true;
        const requiredFields = [this.apiKeyInput, this.tickerInput, this.providerInput, this.startDateInput, this.endDateInput];
        
        requiredFields.forEach(field => {
            field.classList.remove('error');
            if (!field.value.trim()) {
                field.classList.add('error');
                isValid = false;
            }
        });

        this.validateDateRange();
        if (this.endDateInput.validationMessage) {
            isValid = false;
        }

        return isValid;
    }

    setFormLoading(loading) {
        this.submitBtn.disabled = loading;
        if (loading) {
            this.submitBtn.classList.add('loading');
        } else {
            this.submitBtn.classList.remove('loading');
        }
    }

    showStatusMessage(type, message) {
        const messageElement = document.createElement('div');
        messageElement.className = `status-message status-${type} fade-in`;
        messageElement.textContent = message;
        
        this.statusMessages.appendChild(messageElement);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (messageElement.parentNode) {
                messageElement.remove();
            }
        }, 5000);
    }

    clearStatusMessages() {
        this.statusMessages.innerHTML = '';
    }

    async refreshJobs() {
        if (this.isRefreshing) return;
        
        this.isRefreshing = true;
        
        try {
            // Temporary: Show message that job monitoring is coming soon
            this.jobsTableBody.innerHTML = `
                <tr class="no-jobs">
                    <td colspan="8">
                        <div class="empty-state">
                            <h3>🚧 Job Monitoring Coming Soon!</h3>
                            <p>The backfill job creation is working perfectly! 🎉</p>
                            <p>Job monitoring and status tracking will be available in the next update.</p>
                            <p>For now, you can check job progress in the database or through the backfill worker logs.</p>
                        </div>
                    </td>
                </tr>
            `;
            this.updateJobCount(0);
            this.updateLastRefreshTime();
        } catch (error) {
            console.error('Error refreshing jobs:', error);
        } finally {
            this.isRefreshing = false;
        }
    }

    updateJobsTable(jobs) {
        // Update jobs cache and detect changes for active jobs
        const activeJobIds = new Set();
        
        jobs.forEach(job => {
            const previousJob = this.jobs.get(job.job_id);
            this.jobs.set(job.job_id, job);
            
            // Track active jobs for monitoring
            if (job.status === 'PENDING' || job.status === 'RUNNING') {
                activeJobIds.add(job.job_id);
            }
            
            // Check if job status changed
            if (previousJob && previousJob.status !== job.status) {
                this.notifyStatusChange(job, previousJob.status);
            }
        });

        // Update individual job details for active jobs
        this.updateActiveJobDetails(activeJobIds);

        this.renderJobsTable(jobs);
        this.updateJobCount(jobs.length);
    }

    async updateActiveJobDetails(activeJobIds) {
        // Fetch detailed information for active jobs
        const updatePromises = Array.from(activeJobIds).map(async (jobId) => {
            try {
                const response = await fetch(`${this.apiBaseUrl}/backfill/jobs/${jobId}`, {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (response.ok) {
                    const jobDetail = await response.json();
                    this.jobs.set(jobId, jobDetail);
                }
            } catch (error) {
                console.error(`Failed to update job ${jobId}:`, error);
            }
        });

        await Promise.all(updatePromises);
    }

    renderJobsTable(jobs) {
        if (jobs.length === 0) {
            this.jobsTableBody.innerHTML = `
                <tr class="no-jobs">
                    <td colspan="8">
                        <div class="empty-state">
                            <p>No jobs found. Create your first backfill job above.</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        // Sort jobs by creation date (newest first)
        const sortedJobs = jobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        
        this.jobsTableBody.innerHTML = sortedJobs.map(job => this.renderJobRow(job)).join('');
    }

    renderJobRow(job) {
        const dateRange = this.formatDateRange(job.start_date, job.end_date);
        const createdAt = this.formatTimestamp(job.created_at);
        const progress = this.calculateProgress(job);
        const statusBadge = this.renderStatusBadge(job.status);
        
        return `
            <tr data-job-id="${job.job_id}" class="slide-in">
                <td>
                    <span class="job-id" title="${job.job_id}">
                        ${job.job_id.slice(0, 8)}...
                    </span>
                </td>
                <td><strong>${job.ticker}</strong></td>
                <td>${job.provider}</td>
                <td>
                    <div class="date-range">
                        <strong>From:</strong> ${job.start_date}<br>
                        <strong>To:</strong> ${job.end_date}
                    </div>
                </td>
                <td>${statusBadge}</td>
                <td>
                    <div class="progress-container">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress.percentage}%"></div>
                        </div>
                        <small>${progress.text}</small>
                    </div>
                </td>
                <td>
                    <span class="timestamp" title="${job.created_at}">
                        ${createdAt}
                    </span>
                </td>
                <td>
                    <button class="action-btn view" onclick="adminPanel.showJobDetails('${job.job_id}')">
                        View
                    </button>
                    ${job.status === 'PENDING' || job.status === 'RUNNING' ? 
                        `<button class="action-btn cancel" onclick="adminPanel.cancelJob('${job.job_id}')">
                            Cancel
                        </button>` : ''
                    }
                </td>
            </tr>
        `;
    }

    renderStatusBadge(status) {
        const statusClass = status.toLowerCase().replace('_', '-');
        const statusText = status.replace('_', ' ');
        return `<span class="status-badge status-${statusClass}">${statusText}</span>`;
    }

    calculateProgress(job) {
        if (job.status === 'COMPLETED') {
            return { percentage: 100, text: '100%' };
        } else if (job.status === 'FAILED') {
            return { percentage: 0, text: 'Failed' };
        } else if (job.status === 'RUNNING') {
            // Estimate progress based on processed vs total records if available
            if (job.processed_records && job.total_records) {
                const percentage = Math.round((job.processed_records / job.total_records) * 100);
                return { percentage, text: `${percentage}%` };
            }
            return { percentage: 25, text: 'Running...' };
        } else {
            return { percentage: 0, text: 'Pending' };
        }
    }

    formatDateRange(startDate, endDate) {
        return `${startDate} to ${endDate}`;
    }

    formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffMinutes = Math.floor(diffMs / (1000 * 60));
        
        if (diffMinutes < 1) return 'Just now';
        if (diffMinutes < 60) return `${diffMinutes}m ago`;
        if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)}h ago`;
        
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }

    updateJobCount(count) {
        this.jobCountElement.textContent = `${count} job${count !== 1 ? 's' : ''}`;
    }

    updateLastRefreshTime() {
        const now = new Date();
        this.lastRefreshElement.textContent = `Updated ${now.toLocaleTimeString()}`;
    }

    toggleAutoRefresh(enabled) {
        if (enabled) {
            this.startAutoRefresh();
        } else {
            this.stopAutoRefresh();
        }
    }

    startAutoRefresh() {
        if (this.refreshInterval) return;
        
        this.refreshInterval = setInterval(() => {
            this.refreshJobs();
        }, 10000); // Refresh every 10 seconds
    }

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    async showJobDetails(jobId) {
        const job = this.jobs.get(jobId);
        if (!job) return;

        try {
            // Fetch latest job details
            const response = await fetch(`${this.apiBaseUrl}/backfill/jobs/${jobId}`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            let detailedJob = job;
            if (response.ok) {
                detailedJob = await response.json();
                this.jobs.set(jobId, detailedJob); // Update cache
            }

            this.modalTitle.textContent = `Job Details - ${detailedJob.ticker}`;
            this.modalBody.innerHTML = this.renderJobDetailsContent(detailedJob);
            this.modal.classList.remove('hidden');
        } catch (error) {
            console.error('Error fetching job details:', error);
            this.showStatusMessage('error', 'Failed to load job details');
        }
    }

    renderJobDetailsContent(job) {
        const progress = this.calculateProgress(job);
        
        return `
            <div class="job-details">
                <div class="detail-section">
                    <h4>Basic Information</h4>
                    <table class="detail-table">
                        <tr><td><strong>Job ID:</strong></td><td><code>${job.job_id}</code></td></tr>
                        <tr><td><strong>Ticker:</strong></td><td>${job.ticker}</td></tr>
                        <tr><td><strong>Provider:</strong></td><td>${job.provider}</td></tr>
                        <tr><td><strong>Status:</strong></td><td>${this.renderStatusBadge(job.status)}</td></tr>
                        <tr><td><strong>Created:</strong></td><td>${new Date(job.created_at).toLocaleString()}</td></tr>
                    </table>
                </div>

                <div class="detail-section">
                    <h4>Date Range</h4>
                    <table class="detail-table">
                        <tr><td><strong>Start Date:</strong></td><td>${job.start_date}</td></tr>
                        <tr><td><strong>End Date:</strong></td><td>${job.end_date}</td></tr>
                    </table>
                </div>

                <div class="detail-section">
                    <h4>Progress</h4>
                    <div class="progress-container" style="max-width: 100%;">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress.percentage}%"></div>
                        </div>
                        <p style="margin-top: 0.5rem;">${progress.text}</p>
                    </div>
                    ${job.processed_records ? `
                        <table class="detail-table" style="margin-top: 1rem;">
                            <tr><td><strong>Processed Records:</strong></td><td>${job.processed_records.toLocaleString()}</td></tr>
                            <tr><td><strong>Total Records:</strong></td><td>${job.total_records ? job.total_records.toLocaleString() : 'Unknown'}</td></tr>
                        </table>
                    ` : ''}
                </div>

                ${job.error_message ? `
                    <div class="detail-section">
                        <h4>Error Details</h4>
                        <div class="error-details">
                            <code>${job.error_message}</code>
                        </div>
                    </div>
                ` : ''}

                ${job.updated_at ? `
                    <div class="detail-section">
                        <h4>Timestamps</h4>
                        <table class="detail-table">
                            <tr><td><strong>Last Updated:</strong></td><td>${new Date(job.updated_at).toLocaleString()}</td></tr>
                            ${job.completed_at ? `<tr><td><strong>Completed:</strong></td><td>${new Date(job.completed_at).toLocaleString()}</td></tr>` : ''}
                        </table>
                    </div>
                ` : ''}
            </div>

            <style>
                .detail-section {
                    margin-bottom: 2rem;
                }
                .detail-section h4 {
                    margin-bottom: 1rem;
                    color: #374151;
                    border-bottom: 1px solid #e5e7eb;
                    padding-bottom: 0.5rem;
                }
                .detail-table {
                    width: 100%;
                    border-collapse: collapse;
                }
                .detail-table td {
                    padding: 0.5rem 0;
                    border-bottom: 1px solid #f3f4f6;
                }
                .detail-table td:first-child {
                    width: 40%;
                    color: #6b7280;
                }
                .error-details {
                    background: #fef2f2;
                    border: 1px solid #fecaca;
                    border-radius: 6px;
                    padding: 1rem;
                }
                .error-details code {
                    color: #dc2626;
                    font-size: 0.9rem;
                    word-break: break-word;
                }
            </style>
        `;
    }

    closeModal() {
        this.modal.classList.add('hidden');
    }

    async cancelJob(jobId) {
        if (!confirm('Are you sure you want to cancel this job?')) {
            return;
        }

        try {
            const apiKey = localStorage.getItem('finbase_admin_api_key') || this.apiKeyInput.value;
            
            const response = await fetch(`${this.apiBaseUrl}/backfill/jobs/${jobId}/cancel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': apiKey
                }
            });

            if (response.ok) {
                this.showStatusMessage('info', 'Job cancellation requested');
                await this.refreshJobs();
            } else {
                const errorData = await response.json();
                this.showStatusMessage('error', `Failed to cancel job: ${errorData.detail || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Error cancelling job:', error);
            this.showStatusMessage('error', 'Network error: Unable to cancel job');
        }
    }

    clearCompletedJobs() {
        const completedJobs = Array.from(this.jobs.values())
            .filter(job => job.status === 'COMPLETED' || job.status === 'FAILED');
        
        if (completedJobs.length === 0) {
            this.showStatusMessage('info', 'No completed jobs to clear');
            return;
        }

        if (confirm(`Remove ${completedJobs.length} completed job(s) from the display?`)) {
            completedJobs.forEach(job => {
                this.jobs.delete(job.job_id);
            });
            
            const remainingJobs = Array.from(this.jobs.values());
            this.renderJobsTable(remainingJobs);
            this.updateJobCount(remainingJobs.length);
            this.showStatusMessage('success', `Cleared ${completedJobs.length} completed job(s)`);
        }
    }

    notifyStatusChange(job, previousStatus) {
        const statusMessages = {
            'COMPLETED': 'success',
            'FAILED': 'error',
            'RUNNING': 'info',
            'PENDING': 'info'
        };

        const messageType = statusMessages[job.status] || 'info';
        const message = `Job ${job.ticker} (${job.job_id.slice(0, 8)}) changed from ${previousStatus} to ${job.status}`;
        
        this.showStatusMessage(messageType, message);
    }

    // Utility method to handle API errors gracefully
    async handleApiRequest(url, options = {}) {
        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            
            return { response, data: await response.json() };
        } catch (error) {
            console.error('API request failed:', error);
            throw new Error('Network error: Unable to connect to API');
        }
    }
}

// Initialize the admin panel when the page loads
let adminPanel;

document.addEventListener('DOMContentLoaded', () => {
    adminPanel = new AdminPanel();
});

// Export for testing purposes
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AdminPanel;
}
