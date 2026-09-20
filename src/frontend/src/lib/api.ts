// API base URL - will use proxy in development
import logger from '@/lib/logger';
import authService from './authService';
import { handleApiError } from '@/lib/errorHandler';

export interface ApiFile {
    id: string;
    chat_id: number;
    message_id: number;
    file_type: 'document' | 'video' | 'photo' | 'voice' | 'audio';
    thumbnail: string | null;
    file_unique_id: string;
    file_size: number;
    file_name: string | null;
    file_caption: string | null;
    file_path: string;  // Path where file is located
}

export interface FilesResponse {
    files: ApiFile[];
}

export interface UploadFileResponse {
    message: string;
    file: ApiFile;
}

export interface UserProfile {
  username: string;
  email?: string;
  telegram_user_id?: number;
  telegram_username?: string;
  telegram_first_name?: string;
  telegram_last_name?: string;
  telegram_profile_picture?: string;
}

export interface IsOwnerResponse {
  is_owner: boolean;
  owner_telegram_id?: number;
}

export interface UserPermission {
  read: boolean;
  write: boolean;
}

export interface User {
  id: string;
  username: string;
  email?: string;
  telegramUserId?: number;
  telegramUsername?: string;
  permissions: UserPermission;
  createdAt: string;
  lastActive?: string;
  userType?: string;  // "local" or "google"
}

export interface UsersResponse {
  users: User[];
}

export interface AddUserRequest {
  username?: string;
  email?: string;
  password?: string;
  permissions: UserPermission;
}

export interface UpdateUserRequest {
  email?: string;
  permissions: UserPermission;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface IndexChatResponse {
  index_chat_id: number | null;
}

export interface UpdateIndexChatRequest {
  index_chat_id: number | null;
}

export interface CreateFolderRequest {
    folderName: string;
    currentPath: string;
}

export interface CreateFolderPathRequest {
    fullPath: string;
}

const getDefaultApiUrl = () => {
  const savedUrl = localStorage.getItem("serverUrl");
  if (savedUrl) {
    return savedUrl;
  }
  return import.meta.env.VITE_API_URL || '/api';
};

const API_BASE_URL = getDefaultApiUrl();

const SERVER_URL_KEY = "serverUrl";

// Function to get the API base URL
export const getApiBaseUrl = (): string => {
  // Check if there's a custom server URL in localStorage
  const customUrl = localStorage.getItem(SERVER_URL_KEY);
  console.log('[getApiBaseUrl] Checking for custom URL:', customUrl);
  
  if (customUrl) {
    return customUrl;
  }
  
  // Return default URL (port 8148)
  if (typeof window !== 'undefined') {
    // Check if running in Tauri
    const isTauri = authService.isTauri();
    console.log('[getApiBaseUrl] Tauri detection:', isTauri);
    
    if (isTauri) {
      // In Tauri, always use localhost:8148 by default
      console.log('[getApiBaseUrl] Returning Tauri default URL: http://localhost:8148');
      return 'http://localhost:8148';
    }
    
    // For web, use the origin where the app is served
    return window.location.origin;
  }
  
  return import.meta.env.VITE_API_URL || '';
};

// Function to update the API base URL
export const updateApiBaseUrl = (url: string) => {
  if (url) {
    localStorage.setItem(SERVER_URL_KEY, url);
  } else {
    localStorage.removeItem(SERVER_URL_KEY);
  }
};

// Function to reset API base URL to default
export const resetApiBaseUrl = () => {
  localStorage.removeItem(SERVER_URL_KEY);
};

// Function to construct full API URLs
export const getFullApiUrl = (endpoint: string): string => {
  const baseUrl = getApiBaseUrl();
  
  // If we have a custom base URL, append the endpoint
  if (baseUrl) {
    // Ensure the endpoint starts with a slash
    const formattedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    return `${baseUrl}${formattedEndpoint}`;
  }
  
  // For same-origin requests, use the endpoint directly (no /api prefix)
  return endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
};

// Import Tauri HTTP plugin
let http: typeof import('@tauri-apps/plugin-http') | null = null;
let isTauriEnv = false;
let httpReady: Promise<void> | null = null;

// Check if we're running in Tauri (using direct detection to avoid circular dependencies)
if (typeof window !== 'undefined' && (window as any).__TAURI__) {
  isTauriEnv = true;
  logger.info('[API] Detected Tauri environment');
  console.log('[API] Detected Tauri environment with window.__TAURI__:', !!(window as any).__TAURI__);
}

// Dynamically import the HTTP plugin only in Tauri environment
httpReady = import('@tauri-apps/plugin-http').then((module) => {
  http = module;
  logger.info('[API] Tauri HTTP plugin loaded successfully');
}).catch((error) => {
  logger.error('[API] Failed to load Tauri HTTP plugin:', error);
  httpReady = null;
});

// Utility function to add auth headers to fetch options
function addAuthHeaders(options: RequestInit = {}): RequestInit {
  const headers = new Headers(options.headers || {});
  
  // Get authentication headers from authService
  const authHeaders = authService.getAuthHeaders();
  
  // Merge authentication headers
  Object.entries(authHeaders).forEach(([key, value]) => {
    headers.set(key, value);
  });
  
  // Convert Headers object to plain object for Tauri compatibility
  const headersObj: Record<string, string> = {};
  headers.forEach((value, key) => {
    headersObj[key] = value;
  });
  
  return {
    ...options,
    headers: headersObj,
  };
}

// Utility function to implement fetch with timeout
export const fetchWithTimeout = async (url: string, options: RequestInit = {}, timeout: number = 30000): Promise<Response> => {
  // Add auth headers to all requests
  const mergedOptions = addAuthHeaders(options);
  
  // Check if we're running in Tauri (using direct detection to avoid circular dependencies)
  const isTauri = typeof window !== 'undefined' && !!(window as any).__TAURI__;
  
  // For Tauri environment, we don't want to send credentials as they don't work the same way
  let tauriCredentials = (mergedOptions as any).credentials;
  if (isTauri && tauriCredentials === 'include') {
    tauriCredentials = undefined;
  }

  logger.info('[API] fetchWithTimeout called with:', { url, options, mergedOptions, timeout });

  // Use Tauri HTTP plugin if available (in Tauri environment)
  if (isTauriEnv) {
    logger.info('[API] Running in Tauri environment');
    try {
      // Wait for Tauri HTTP plugin to load if it's still loading
      if (httpReady) {
        logger.info('[API] Waiting for Tauri HTTP plugin to load');
        await httpReady;
      }
      
      if (http) {
        logger.info('[API] Using Tauri HTTP plugin for request to:', url);
        // Make the request using Tauri's HTTP plugin
        const response = await http.fetch(url, {
          method: mergedOptions.method || 'GET',
          headers: mergedOptions.headers,
          body: mergedOptions.body instanceof FormData ? mergedOptions.body : (typeof mergedOptions.body === 'string' ? mergedOptions.body : (mergedOptions.body ? JSON.stringify(mergedOptions.body) : undefined)),
          credentials: isTauriEnv && tauriCredentials === 'include' ? undefined : (tauriCredentials === 'include' ? 'include' : 'omit'),
        });
        
        logger.info('[API] Tauri HTTP response status:', response.status);
        // Return the response directly as it's already a standard Response object
        return response;
      } else {
        logger.warn('[API] Tauri HTTP plugin not available after waiting, falling back to standard fetch');
      }
    } catch (error) {
      logger.error('[API] Tauri HTTP request failed, falling back to standard fetch:', error);
    }
    
    // Fall back to standard fetch if Tauri HTTP plugin fails
    logger.info('[API] Falling back to standard fetch for request to:', url);
  }
  
  // Standard browser fetch with timeout (for non-Tauri environments)
  logger.info('[API] Using standard fetch for request to:', url);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort(new Error(`Request timed out after ${Math.round(timeout / 1000)}s`));
  }, timeout);
  
  try {
    logger.info('[API] Making fetch request with options:', mergedOptions);
    const response = await fetch(url, {
      ...mergedOptions,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    logger.info('[API] Standard fetch response status:', response.status);
    return response;
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error?.name === 'AbortError' || error?.message?.toLowerCase().includes('aborted')) {
      logger.error('[API] Request timed out or was aborted:', { url, timeout });
      throw new Error(`Request timed out after ${Math.round(timeout / 1000)}s. Please try again.`);
    }
    logger.error('[API] Standard fetch error:', error);
    throw error;
  }
};

export const api = {
    async fetchFiles(path: string = '/'): Promise<FilesResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/files?path=${encodeURIComponent(path)}`, fetchOptions, 3000); // 3 second timeout

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to fetch files: ${response.statusText}`);
        }

        return response.json();
    },

    async checkAuth() {
        const baseUrl = getApiBaseUrl();
        // For the default case, we use the base URL directly (no /api prefix)
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/auth/check`, fetchOptions, 3000); // 3 second timeout

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to check auth: ${response.statusText}`);
        }

        return response.json();
    },

    async logout() {
        const baseUrl = getApiBaseUrl();
        // For the default case, we use the base URL directly (no /api prefix)
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'POST',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/auth/logout`, fetchOptions, 3000); // 3 second timeout

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to logout: ${response.statusText}`);
        }

        // Clear auth token from localStorage
        if (typeof window !== 'undefined') {
            localStorage.removeItem('auth_token');
        }

        return response.json();
    },

    async fetchUserProfile(): Promise<UserProfile> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/profile`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to fetch user profile: ${response.statusText}`);
        }

        const data = await response.json();
        
        // Map snake_case fields to camelCase
        const userProfile: UserProfile = {
            username: data.username,
            email: data.email,
            telegram_user_id: data.telegram_user_id,
            telegram_username: data.telegram_username,
            telegram_first_name: data.telegram_first_name,
            telegram_last_name: data.telegram_last_name,
            telegram_profile_picture: data.telegram_profile_picture
        };
        
        return userProfile;
    },    async isUserOwner(): Promise<IsOwnerResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/is-owner`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to check owner status: ${response.statusText}`);
        }

        const data = await response.json();
        
        // Map snake_case fields to camelCase
        const isOwnerResponse: IsOwnerResponse = {
            is_owner: data.is_owner,
            owner_telegram_id: data.owner_telegram_id
        };
        
        return isOwnerResponse;
    },

    async getUsers(): Promise<UsersResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to fetch users: ${response.statusText}`);
        }

        const data = await response.json();
        
        // Map snake_case fields to camelCase
        const usersResponse: UsersResponse = {
            users: data.users.map((user: any) => ({
                id: user.id,
                username: user.username,
                email: user.email,
                telegramUserId: user.telegram_user_id,
                telegramUsername: user.telegram_username,
                permissions: user.permissions,
                createdAt: user.created_at,
                lastActive: user.last_active,
                userType: user.user_type
            }))
        };
        
        return usersResponse;
    },
    async addUser(userData: AddUserRequest): Promise<User> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify(userData),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to add user: ${response.statusText}`);
        }

        return response.json();
    },

    async updateUser(userId: string, userData: UpdateUserRequest): Promise<User> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify(userData),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/${userId}`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to update user: ${response.statusText}`);
        }

        return response.json();
    },

    async deleteUser(userId: string): Promise<void> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'DELETE',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/${userId}`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to delete user: ${response.statusText}`);
        }
    },

    async changeUserPassword(userId: string, passwordData: ChangePasswordRequest): Promise<{ message: string }> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify(passwordData),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/${userId}/password`, fetchOptions, 5000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            
            const errorText = await response.text();
            throw new Error(errorText || `Failed to change user password: ${response.status}`);
        }

        return response.json();
    },

    async getUserIndexChat(): Promise<IndexChatResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'GET',
            headers: authService.getAuthHeaders(),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/index-chat`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to fetch index chat: ${response.statusText}`);
        }

        return response.json();
    },

    async updateUserIndexChat(indexChatData: UpdateIndexChatRequest): Promise<IndexChatResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify(indexChatData),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/user/index-chat`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to update index chat: ${response.statusText}`);
        }

        return response.json();
    },

    async uploadFileChunked(
        file: File,
        path: string = '/',
        onProgress?: (percent: number, loaded: number, total: number, speed?: string, eta?: string) => void
    ): Promise<UploadFileResponse> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        const authHeaders = authService.getAuthHeaders();

        // Step 1: Init chunked upload
        const initRes = await fetch(`${apiUrl}/files/upload/init`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authHeaders,
            },
            credentials: 'include',
            body: JSON.stringify({
                filename: file.name,
                filesize: file.size,
                path: path || '/Home'
            })
        });

        if (!initRes.ok) {
            const errData = await initRes.json().catch(() => ({}));
            throw new Error(errData.detail || 'Failed to initialize chunked upload');
        }

        const initData = await initRes.json();
        const uploadId = initData.upload_id;
        const CHUNK_SIZE = initData.chunk_size || 20 * 1024 * 1024;
        const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

        let bytesUploaded = 0;
        let lastTime = Date.now();
        let lastLoaded = 0;
        let currentSpeed = 0;

        const formatSpeed = (bytesPerSec: number): string => {
            if (bytesPerSec <= 0) return '0 B/s';
            const k = 1024;
            const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
            const i = Math.floor(Math.log(bytesPerSec) / Math.log(k));
            return parseFloat((bytesPerSec / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        };

        const formatEta = (seconds: number): string => {
            if (!isFinite(seconds) || seconds <= 0) return '';
            if (seconds > 3600) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
            if (seconds > 60) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
            return `${Math.round(seconds)}s`;
        };

        // Step 2: Upload chunks sequentially with auto-retry
        for (let chunkIdx = 0; chunkIdx < totalChunks; chunkIdx++) {
            const start = chunkIdx * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunkBlob = file.slice(start, end);

            let success = false;
            let lastErr: any = null;

            for (let attempt = 0; attempt < 3; attempt++) {
                try {
                    const chunkFormData = new FormData();
                    chunkFormData.append('upload_id', uploadId);
                    chunkFormData.append('chunk_index', chunkIdx.toString());
                    chunkFormData.append('chunk_file', chunkBlob, file.name);

                    const chunkRes = await fetch(`${apiUrl}/files/upload/chunk`, {
                        method: 'POST',
                        headers: {
                            ...authHeaders
                        },
                        credentials: 'include',
                        body: chunkFormData
                    });

                    if (!chunkRes.ok) {
                        const errData = await chunkRes.json().catch(() => ({}));
                        throw new Error(errData.detail || `Chunk upload failed (${chunkRes.status})`);
                    }

                    success = true;
                    bytesUploaded += (end - start);

                    const now = Date.now();
                    const timeDiff = (now - lastTime) / 1000;
                    if (timeDiff >= 0.3) {
                        const bytesDiff = bytesUploaded - lastLoaded;
                        const instantSpeed = bytesDiff / timeDiff;
                        currentSpeed = currentSpeed === 0 ? instantSpeed : 0.7 * currentSpeed + 0.3 * instantSpeed;
                        lastTime = now;
                        lastLoaded = bytesUploaded;
                    }

                    if (onProgress) {
                        const percent = Math.min(99, Math.round((bytesUploaded / file.size) * 100));
                        const remaining = file.size - bytesUploaded;
                        const etaSec = currentSpeed > 0 ? remaining / currentSpeed : 0;
                        onProgress(percent, bytesUploaded, file.size, formatSpeed(currentSpeed), formatEta(etaSec));
                    }
                    break;
                } catch (err) {
                    lastErr = err;
                    await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
                }
            }

            if (!success) {
                throw new Error(`Failed to upload chunk ${chunkIdx + 1}/${totalChunks}: ${lastErr?.message || 'Network error'}`);
            }
        }

        // Step 3: Trigger completion (processed in background on server)
        const completeFormData = new FormData();
        completeFormData.append('upload_id', uploadId);

        let initialResponseData: any = null;
        try {
            const completeRes = await fetch(`${apiUrl}/files/upload/complete`, {
                method: 'POST',
                headers: {
                    ...authHeaders
                },
                credentials: 'include',
                body: completeFormData
            });

            if (completeRes.ok) {
                initialResponseData = await completeRes.json().catch(() => null);
            }
        } catch (fetchErr) {
            logger.warn('[API] /files/upload/complete connection dropped, checking status...', fetchErr);
        }

        // Fast path: if already completed
        if (initialResponseData?.status === 'completed' && initialResponseData?.file) {
            if (onProgress) {
                onProgress(100, file.size, file.size, '', '');
            }
            return {
                message: initialResponseData.message || 'File uploaded successfully',
                file: initialResponseData.file
            };
        }

        // Step 4: Poll status until complete (handles large files saving to Telegram cloud)
        if (onProgress) {
            onProgress(99, file.size, file.size, 'Saving to Telegram cloud...', '');
        }

        const pollIntervalMs = 2000;
        const maxPollTimeMs = 30 * 60 * 1000; // 30 minutes max for large files
        const startTime = Date.now();

        while (Date.now() - startTime < maxPollTimeMs) {
            await new Promise(resolve => setTimeout(resolve, pollIntervalMs));

            try {
                const statusRes = await fetch(`${apiUrl}/files/upload/status/${uploadId}`, {
                    headers: {
                        ...authHeaders
                    },
                    credentials: 'include'
                });

                if (statusRes.ok) {
                    const statusData = await statusRes.json();
                    if (statusData.status === 'completed') {
                        if (onProgress) {
                            onProgress(100, file.size, file.size, '', '');
                        }
                        return {
                            message: statusData.message || 'File uploaded successfully',
                            file: statusData.file
                        };
                    } else if (statusData.status === 'error') {
                        throw new Error(statusData.error || 'Upload failed while saving to Telegram');
                    } else {
                        // Still processing
                        if (onProgress) {
                            onProgress(99, file.size, file.size, 'Saving to Telegram cloud...', '');
                        }
                    }
                } else if (statusRes.status === 404) {
                    throw new Error('Upload session expired or not found');
                }
            } catch (err: any) {
                if (err.message && (err.message.includes('saving to Telegram') || err.message.includes('expired or not found'))) {
                    throw err;
                }
                logger.warn('[API] Polling upload status transient error:', err);
            }
        }

        throw new Error('Upload completion timed out. Please check your drive.');
    },

    async uploadFile(
        file: File, 
        path: string = '/',
        onProgress?: (percent: number, loaded: number, total: number, speed?: string, eta?: string) => void
    ): Promise<UploadFileResponse> {
        // Automatically use chunked uploader for large files (> 50MB) for maximum resilience
        if (file.size > 50 * 1024 * 1024) {
            return this.uploadFileChunked(file, path, onProgress);
        }

        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', path);
        
        return new Promise<UploadFileResponse>((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${apiUrl}/files/upload`, true);
            xhr.withCredentials = true;
            
            // Add auth headers
            const authHeaders = authService.getAuthHeaders();
            Object.entries(authHeaders).forEach(([key, value]) => {
                xhr.setRequestHeader(key, value);
            });
            
            let lastTime = Date.now();
            let lastLoaded = 0;
            let currentSpeed = 0;
            let lastCallbackTime = 0;

            const formatSpeed = (bytesPerSec: number): string => {
                if (bytesPerSec <= 0) return '0 B/s';
                const k = 1024;
                const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
                const i = Math.floor(Math.log(bytesPerSec) / Math.log(k));
                return parseFloat((bytesPerSec / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
            };

            const formatEta = (seconds: number): string => {
                if (!isFinite(seconds) || seconds <= 0) return '';
                if (seconds > 3600) {
                    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
                }
                if (seconds > 60) {
                    return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
                }
                return `${Math.round(seconds)}s`;
            };

            // Track real upload progress (0% to 99% while sending data to server)
            if (xhr.upload && onProgress) {
                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable && event.total > 0) {
                        const now = Date.now();
                        const timeDiff = (now - lastTime) / 1000;

                        if (timeDiff >= 0.3) {
                            const bytesDiff = event.loaded - lastLoaded;
                            const instantSpeed = bytesDiff / timeDiff;
                            currentSpeed = currentSpeed === 0 ? instantSpeed : 0.7 * currentSpeed + 0.3 * instantSpeed;
                            lastTime = now;
                            lastLoaded = event.loaded;
                        }

                        // Throttle progress state updates to every 250ms for smooth rendering
                        if (now - lastCallbackTime >= 250 || event.loaded === event.total) {
                            lastCallbackTime = now;
                            const percent = Math.min(99, Math.round((event.loaded / event.total) * 100));
                            const remainingBytes = event.total - event.loaded;
                            const etaSeconds = currentSpeed > 0 ? remainingBytes / currentSpeed : 0;
                            const speedStr = currentSpeed > 0 ? formatSpeed(currentSpeed) : '';
                            const etaStr = etaSeconds > 0 ? formatEta(etaSeconds) : '';
                            
                            onProgress(percent, event.loaded, event.total, speedStr, etaStr);
                        }
                    }
                };
            }
            
            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    if (onProgress) {
                        onProgress(100, file.size, file.size, '', '');
                    }
                    try {
                        const data = JSON.parse(xhr.responseText);
                        resolve(data);
                    } catch (e) {
                        resolve({ message: "File uploaded successfully" } as any);
                    }
                } else if (xhr.status === 401) {
                    reject(new Error("Authentication required. Please log in again."));
                } else {
                    let errorMessage = `Failed to upload file: ${xhr.statusText || xhr.status}`;
                    try {
                        const errorData = JSON.parse(xhr.responseText);
                        if (errorData.detail) {
                            errorMessage = errorData.detail;
                        }
                    } catch (_) {}
                    reject(new Error(errorMessage));
                }
            };
            
            xhr.onerror = () => {
                reject(new Error("Network error during file upload. Please check your connection."));
            };
            
            xhr.onabort = () => {
                reject(new Error("Upload aborted."));
            };
            
            // No premature timeout: let large files complete as long as data transfers
            xhr.timeout = 0;
            
            xhr.send(formData);
        });
    },

    async createFolder(folderName: string, currentPath: string): Promise<{ message: string }> {
        const baseUrl = getApiBaseUrl();
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify({ folderName, currentPath }),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/folders/create`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to create folder: ${response.statusText}`);
        }

        return response.json();
    },

    async createFolderPath(fullPath: string): Promise<{ message: string }> {
        const baseUrl = getApiBaseUrl();
        // For the default case, we use the base URL directly (no /api prefix)
        const apiUrl = baseUrl ? `${baseUrl}` : '';
        
        // Prepare fetch options
        const fetchOptions: RequestInit = {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authService.getAuthHeaders()
            },
            body: JSON.stringify({ fullPath }),
        };
        
        const response = await fetchWithTimeout(`${apiUrl}/folders/create-path`, fetchOptions, 3000);

        if (!response.ok) {
            // Handle specific error cases
            if (response.status === 401) {
                throw new Error("Authentication required. Please log in again.");
            }
            throw new Error(`Failed to create folder path: ${response.statusText}`);
        }

        return response.json();
    },

    async toggleStar(fileId: string, starred?: boolean): Promise<{ starred: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/star`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId, starred }),
        });

        if (!response.ok) {
            throw new Error('Failed to update star status');
        }

        return response.json();
    },

    async trashFile(fileId: string): Promise<{ message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/trash`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to move item to trash');
        }

        return response.json();
    },

    async restoreFile(fileId: string): Promise<{ message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/restore`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to restore item from trash');
        }

        return response.json();
    },

    async emptyTrash(): Promise<{ message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/trash/empty`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to empty trash');
        }

        return response.json();
    },

    async deleteForever(fileId: string): Promise<{ message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/delete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Failed to permanently delete item');
        }

        return response.json();
    },

    async getStorageAnalytics(): Promise<any> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/files/analytics`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
        });

        if (!response.ok) {
            throw new Error('Failed to fetch storage analytics');
        }

        return response.json();
    },

    async getVaultStatus(): Promise<{ is_setup: boolean; is_unlocked: boolean; email?: string; remaining_seconds?: number }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/status`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        });
        if (!response.ok) {
            throw new Error('Failed to fetch vault status');
        }
        return response.json();
    },

    async requestVaultSetupOtp(email: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/setup/request-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to send verification code');
        }
        return response.json();
    },

    async verifyVaultOtp(otp_code: string, purpose: string = 'Private Vault Setup', email?: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/verify-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ otp_code, purpose, email }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Invalid verification code');
        }
        return response.json();
    },

    async verifyAndCreateVault(email: string, otp_code: string, pin: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/setup/verify-and-create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email, otp_code, pin }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create vault');
        }
        return response.json();
    },

    async unlockVault(pin: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/unlock`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ pin }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Incorrect PIN');
        }
        return response.json();
    },

    async lockVault(): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/lock`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        });
        if (!response.ok) {
            throw new Error('Failed to lock vault');
        }
        return response.json();
    },

    async requestForgotPinOtp(): Promise<{ success: boolean; message: string; masked_email?: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/forgot-pin/request-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to request reset code');
        }
        return response.json();
    },

    async resetVaultPin(otp_code: string, new_pin: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/forgot-pin/reset`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ otp_code, new_pin }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to reset PIN');
        }
        return response.json();
    },

    async moveIntoVault(fileId: string, targetPath: string = '/Vault'): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/move-in`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId, target_path: targetPath }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to move item to Vault');
        }
        return response.json();
    },

    async moveOutOfVault(fileId: string, targetPath: string = '/Home'): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/move-out`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ file_id: fileId, target_path: targetPath }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to move item out of Vault');
        }
        return response.json();
    },

    async createVaultFolder(folderName: string, currentPath: string = '/Vault'): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/vault/create-folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ folder_name: folderName, current_path: currentPath }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create folder in Vault');
        }
        return response.json();
    },

    async addRemoteTransfer(url: string, destination_path: string = '/Home'): Promise<{ success: boolean; message: string; count: number; tasks: any[] }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/transfers/remote/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ url, destination_path }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to start remote transfer');
        }
        return response.json();
    },

    async getRemoteTasks(): Promise<{ tasks: any[] }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/transfers/remote/tasks`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        });
        if (!response.ok) {
            return { tasks: [] };
        }
        return response.json();
    },

    async cancelRemoteTask(task_id: string): Promise<{ success: boolean; message: string }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/transfers/remote/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ task_id }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to cancel remote transfer');
        }
        return response.json();
    },

    async clearCompletedRemoteTasks(): Promise<{ success: boolean; cleared_count: number }> {
        const response = await fetchWithTimeout(`${getApiBaseUrl()}/transfers/remote/clear-completed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to clear completed tasks');
        }
        return response.json();
    },
};