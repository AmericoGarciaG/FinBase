# FinBase Admin Frontend Dockerfile
# Multi-stage build for production-ready nginx deployment with API proxy

# Stage 1: Build stage (optional for future expansion with build tools)
FROM node:18-alpine AS builder

# Set working directory
WORKDIR /app

# Copy source files
COPY index.html style.css script.js ./

# For future: if we add build tools like minification, bundling, etc.
# RUN npm install && npm run build

# Stage 2: Production stage with nginx
FROM nginx:1.25-alpine

# Remove default nginx website
RUN rm -rf /usr/share/nginx/html/*

# Copy static files from builder stage (or directly)
COPY index.html style.css script.js /usr/share/nginx/html/

# Create nginx configuration for API proxy
COPY <<EOF /etc/nginx/conf.d/default.conf
# FinBase Admin Frontend Nginx Configuration

upstream api_backend {
    server api-service:8000;
}

server {
    listen 80;
    server_name localhost;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Serve static files
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
        
        # Disable cache for development
        location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg)$ {
            expires -1;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
            add_header Pragma "no-cache";
            add_header Expires "0";
        }
    }

    # Proxy API requests to api-service
    location /api/ {
        # Remove /api prefix and proxy to backend
        rewrite ^/api/(.*) /\$1 break;
        
        proxy_pass http://api_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # API-specific timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        
        # Handle CORS if needed
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Accept, Authorization, Content-Type, X-API-Key" always;
        
        # Handle preflight requests
        if (\$request_method = 'OPTIONS') {
            add_header Access-Control-Allow-Origin "*";
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
            add_header Access-Control-Allow-Headers "Accept, Authorization, Content-Type, X-API-Key";
            add_header Access-Control-Max-Age 1728000;
            add_header Content-Type "text/plain charset=UTF-8";
            add_header Content-Length 0;
            return 204;
        }
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Error pages
    error_page 404 /404.html;
    error_page 500 502 503 504 /50x.html;
    
    location = /404.html {
        root /usr/share/nginx/html;
        internal;
    }
    
    location = /50x.html {
        root /usr/share/nginx/html;
        internal;
    }

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log warn;
}
EOF

# Create simple error pages
COPY <<EOF /usr/share/nginx/html/404.html
<!DOCTYPE html>
<html>
<head>
    <title>404 - Page Not Found</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
        h1 { color: #667eea; }
    </style>
</head>
<body>
    <h1>404 - Page Not Found</h1>
    <p>The requested page could not be found.</p>
    <a href="/">← Back to Admin Panel</a>
</body>
</html>
EOF

COPY <<EOF /usr/share/nginx/html/50x.html
<!DOCTYPE html>
<html>
<head>
    <title>500 - Server Error</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
        h1 { color: #ef4444; }
    </style>
</head>
<body>
    <h1>500 - Server Error</h1>
    <p>An internal server error occurred.</p>
    <a href="/">← Back to Admin Panel</a>
</body>
</html>
EOF

# Set correct permissions
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/health || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
