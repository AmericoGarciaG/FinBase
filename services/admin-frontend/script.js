// FinBase Admin Panel - JavaScript Logic

class AdminPanel {
    constructor() {
        this.apiBaseUrl = '/api/v1';
        this.jobs = new Map();
        this.refreshInterval = null;
        this.isRefreshing = false;
        
        this.initializeElements();
        this.attachEventListeners();
        this.initializeAppWithRetries();
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

        // On page unload: attempt to resume collectors without API key using sendBeacon
        window.addEventListener('beforeunload', () => {
            try {
                const blob = new Blob([JSON.stringify({})], { type: 'application/json' });
                navigator.sendBeacon(`${this.apiBaseUrl}/collectors/resume`, blob);
            } catch (e) {
                // Ignore errors in unload handler
            }
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

    async initializeAppWithRetries(maxRetries = 6, delayMs = 2000) {
        // Perform the same initialization, but retry connection a few times
        // Set defaults first
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - 30);
        this.startDateInput.value = startDate.toISOString().split('T')[0];
        this.endDateInput.value = endDate.toISOString().split('T')[0];

        const savedApiKey = localStorage.getItem('finbase_admin_api_key');
        if (savedApiKey) {
            this.apiKeyInput.value = savedApiKey;
        }

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            const ok = await this.checkApiConnection();
            if (ok) {
                // Clear any previous error banners upon success
                this.clearStatusMessages();

                // After successful API connection, request collectors to pause (privileged)
                try {
                    const apiKey = localStorage.getItem('finbase_admin_api_key') || this.apiKeyInput.value;
                    if (apiKey) {
                        await fetch(`${this.apiBaseUrl}/collectors/pause`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-API-Key': apiKey
                            },
                            body: JSON.stringify({})
                        });
                    }
                } catch (e) {
                    console.warn('Failed to send pause command:', e);
                }

                await this.refreshJobs();
                if (this.autoRefreshCheckbox.checked) {
                    this.startAutoRefresh();
                }
                return;
            }
            if (attempt < maxRetries) {
                // Do not show a red banner yet; keep UI in 'checking' state and retry silently
                await this.sleep(delayMs);
            }
        }
        // After final failure, show a persistent message
        this.showStatusMessage('error', 'API is unavailable or not ready after multiple attempts. Please verify backend services and retry.', true);
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async checkApiConnection() {
        try {
            this.updateConnectionStatus('checking', 'Checking API connection...');
            
            const response = await fetch(`${this.apiBaseUrl}/ready`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            if (response.ok) {
                // If body has {ready:true} we mark connected
                try {
                    const body = await response.json();
                    if (body && body.ready === true) {
                        this.updateConnectionStatus('connected', 'API Connected');
                        return true;
                    }
                } catch (_) { /* ignore parse issues */ }
                this.updateConnectionStatus('error', 'API Not Ready');
                return false;
            } else {
                this.updateConnectionStatus('error', 'API Not Ready');
                return false;
            }
        } catch (error) {
            this.updateConnectionStatus('error', 'API Unavailable');
            console.error('API connection check failed:', error);
            return false;
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
                // Handle both new architecture responses and legacy ones
                const jobId = responseData.master_job_id || responseData.job_id;
                const apiMessage = responseData.message || 'Job created successfully!';
                const fullMessage = `${apiMessage} (Job ID: ${jobId})`;
                this.showStatusMessage('success', fullMessage);
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

    showStatusMessage(type, message, persist = false) {
        const messageElement = document.createElement('div');
        messageElement.className = `status-message status-${type} fade-in`;
        messageElement.textContent = message;
        
        this.statusMessages.appendChild(messageElement);
        
        if (!persist) {
            // Auto-remove after 5 seconds
            setTimeout(() => {
                if (messageElement.parentNode) {
                    messageElement.remove();
                }
            }, 5000);
        }
    }

    clearStatusMessages() {
        this.statusMessages.innerHTML = '';
    }

    async refreshJobs() {
        if (this.isRefreshing) return;
        
        this.isRefreshing = true;
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/backfill/jobs`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            if (response.ok) {
                const data = await response.json();
                this.updateJobsTable(data.jobs || []);
                this.updateLastRefreshTime();
            } else {
                console.error('Failed to fetch jobs:', response.statusText);
                this.showStatusMessage('error', 'Failed to load jobs');
                this.jobsTableBody.innerHTML = `
                    <tr class="no-jobs">
                        <td colspan="8">
                            <div class="empty-state">
                                <p>❌ Failed to load jobs. Please try again later.</p>
                            </div>
                        </td>
                    </tr>
                `;
            }
        } catch (error) {
            console.error('Error refreshing jobs:', error);
            this.showStatusMessage('error', 'Network error: Unable to connect to API service');
            this.jobsTableBody.innerHTML = `
                <tr class="no-jobs">
                    <td colspan="8">
                        <div class="empty-state">
                            <p>🔌 Network error: Unable to connect to API service</p>
                        </div>
                    </td>
                </tr>
            `;
        } finally {
            this.isRefreshing = false;
        }
    }

    updateJobsTable(jobs) {
        // Update jobs cache and detect changes for active jobs
        const activeJobIds = new Set();
        
        jobs.forEach(job => {
            const previousJob = this.jobs.get(job.id);
            this.jobs.set(job.id, job);
            
            // Track active jobs for monitoring
            if (job.status === 'PENDING' || job.status === 'RUNNING') {
                activeJobIds.add(job.id);
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
        const sortedJobs = jobs.sort((a, b) => new Date(b.submitted_at) - new Date(a.submitted_at));
        
        this.jobsTableBody.innerHTML = sortedJobs.map(job => this.renderJobRow(job)).join('');
    }

    renderJobRow(job) {
        const dateRange = this.formatDateRange(job.start_date, job.end_date);
        const createdAt = this.formatTimestamp(job.submitted_at);
        const progress = this.calculateProgress(job);
        const statusBadge = this.renderStatusBadge(job.status);
        
        return `
            <tr data-job-id="${job.id}" class="slide-in">
                <td>
                    <span class="job-id" title="${job.id}">
                        ${job.id.slice(0, 8)}...
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
                    <span class="timestamp" title="${job.submitted_at}">
                        ${createdAt}
                    </span>
                </td>
                <td>
                    <button class="action-btn view" onclick="adminPanel.showJobDetails('${job.id}')">
                        View
                    </button>
                    ${job.status === 'PENDING' || job.status === 'RUNNING' ? 
                        `<button class="action-btn cancel" onclick="adminPanel.cancelJob('${job.id}')">
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

    calculateDuration(startedAt, completedAt) {
        if (!startedAt) return '-';
        
        const startTime = new Date(startedAt);
        const endTime = completedAt ? new Date(completedAt) : new Date();
        const durationMs = endTime - startTime;
        
        if (durationMs < 0) return '-';
        
        const seconds = Math.floor(durationMs / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        
        if (hours > 0) {
            return `${hours}h ${minutes % 60}m`;
        } else if (minutes > 0) {
            return `${minutes}m ${seconds % 60}s`;
        } else {
            return `${seconds}s`;
        }
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
        
        // Check if this is a detailed job response with sub-jobs
        const isDetailedJob = job.master_job && job.sub_jobs;
        const masterJob = isDetailedJob ? job.master_job : job;
        const subJobs = isDetailedJob ? job.sub_jobs : [];
        const progressSummary = isDetailedJob ? job.progress_summary : {};
        
        return `
            <div class="job-details">
                <div class="detail-section">
                    <h4>Basic Information</h4>
                    <table class="detail-table">
                        <tr><td><strong>Job ID:</strong></td><td><code>${masterJob.id}</code></td></tr>
                        <tr><td><strong>Ticker:</strong></td><td>${masterJob.ticker}</td></tr>
                        <tr><td><strong>Provider:</strong></td><td>${masterJob.provider}</td></tr>
                        <tr><td><strong>Status:</strong></td><td>${this.renderStatusBadge(masterJob.status)}</td></tr>
                        <tr><td><strong>Created:</strong></td><td>${new Date(masterJob.submitted_at).toLocaleString()}</td></tr>
                        ${masterJob.total_sub_jobs ? `<tr><td><strong>Total Sub-jobs:</strong></td><td>${masterJob.total_sub_jobs}</td></tr>` : ''}
                    </table>
                </div>

                <div class="detail-section">
                    <h4>Date Range</h4>
                    <table class="detail-table">
                        <tr><td><strong>Start Date:</strong></td><td>${masterJob.start_date}</td></tr>
                        <tr><td><strong>End Date:</strong></td><td>${masterJob.end_date}</td></tr>
                    </table>
                </div>

                <div class="detail-section">
                    <h4>Progress Overview</h4>
                    <div class="progress-container" style="max-width: 100%;">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress.percentage}%"></div>
                        </div>
                        <p style="margin-top: 0.5rem;">${progress.text}</p>
                    </div>
                    
                    ${Object.keys(progressSummary).length > 0 ? `
                        <div class="progress-summary">
                            <h5>Sub-jobs Status:</h5>
                            <div class="status-chips">
                                ${Object.entries(progressSummary).map(([status, count]) => 
                                    `<span class="status-chip status-${status.toLowerCase()}">${status}: ${count}</span>`
                                ).join('')}
                            </div>
                        </div>
                    ` : ''}
                    
                    ${masterJob.message ? `
                        <div class="job-message">
                            <strong>Planning Details:</strong><br>
                            <span>${masterJob.message}</span>
                        </div>
                    ` : ''}
                </div>

                ${subJobs.length > 0 ? `
                    <div class="detail-section">
                        <h4>Sub-jobs Details (${subJobs.length} total)</h4>
                        <div class="sub-jobs-container">
                            <table class="sub-jobs-table">
                                <thead>
                                    <tr>
                                        <th>ID</th>
                                        <th>Date Range</th>
                                        <th>Status</th>
                                        <th>Records</th>
                                        <th>Duration</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${subJobs.map(subJob => `
                                        <tr class="sub-job-row status-${subJob.status.toLowerCase()}">
                                            <td><code>${subJob.id.slice(0, 8)}...</code></td>
                                            <td>${subJob.start_date} to ${subJob.end_date}</td>
                                            <td>${this.renderStatusBadge(subJob.status)}</td>
                                            <td>${subJob.records_published ? subJob.records_published.toLocaleString() : '0'}</td>
                                            <td>${this.calculateDuration(subJob.started_at, subJob.completed_at)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ` : ''}

                ${masterJob.error_message ? `
                    <div class="detail-section">
                        <h4>Error Details</h4>
                        <div class="error-details">
                            <code>${masterJob.error_message}</code>
                        </div>
                    </div>
                ` : ''}

                <div class="detail-section">
                    <h4>Timestamps</h4>
                    <table class="detail-table">
                        <tr><td><strong>Submitted:</strong></td><td>${new Date(masterJob.submitted_at).toLocaleString()}</td></tr>
                        ${masterJob.started_at ? `<tr><td><strong>Started:</strong></td><td>${new Date(masterJob.started_at).toLocaleString()}</td></tr>` : ''}
                        ${masterJob.completed_at ? `<tr><td><strong>Completed:</strong></td><td>${new Date(masterJob.completed_at).toLocaleString()}</td></tr>` : ''}
                    </table>
                </div>
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
                .progress-summary {
                    margin-top: 1rem;
                }
                .progress-summary h5 {
                    margin-bottom: 0.5rem;
                    color: #4b5563;
                }
                .status-chips {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.5rem;
                }
                .status-chip {
                    padding: 0.25rem 0.5rem;
                    border-radius: 0.25rem;
                    font-size: 0.75rem;
                    font-weight: 500;
                }
                .status-chip.status-pending {
                    background: #fef3c7;
                    color: #92400e;
                }
                .status-chip.status-running {
                    background: #dbeafe;
                    color: #1e40af;
                }
                .status-chip.status-completed {
                    background: #d1fae5;
                    color: #065f46;
                }
                .status-chip.status-failed {
                    background: #fee2e2;
                    color: #b91c1c;
                }
                .job-message {
                    margin-top: 1rem;
                    padding: 0.75rem;
                    background: #f3f4f6;
                    border-radius: 0.5rem;
                    font-size: 0.9rem;
                }
                .sub-jobs-container {
                    max-height: 300px;
                    overflow-y: auto;
                    border: 1px solid #e5e7eb;
                    border-radius: 0.5rem;
                }
                .sub-jobs-table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 0.875rem;
                }
                .sub-jobs-table th {
                    background: #f9fafb;
                    padding: 0.75rem 0.5rem;
                    text-align: left;
                    font-weight: 600;
                    color: #374151;
                    border-bottom: 1px solid #e5e7eb;
                    position: sticky;
                    top: 0;
                }
                .sub-jobs-table td {
                    padding: 0.5rem;
                    border-bottom: 1px solid #f3f4f6;
                }
                .sub-job-row.status-completed {
                    background: #f0fdf4;
                }
                .sub-job-row.status-failed {
                    background: #fef2f2;
                }
                .sub-job-row.status-running {
                    background: #eff6ff;
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
            .filter(job => job.status === 'COMPLETED' || job.status === 'FAILED' || job.status === 'PARTIALLY_COMPLETED');
        
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
