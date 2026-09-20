/**
 * TRAFFICINTEL AI - Central API Client
 * Strictly interfaces with FastAPI /api/v1 endpoints.
 */

const API_BASE = '/api/v1';

export function getAuthToken(): string | null {
  return localStorage.getItem('trafficintel_token');
}

export function setAuthToken(token: string): void {
  localStorage.setItem('trafficintel_token', token);
}

export function removeAuthToken(): void {
  localStorage.removeItem('trafficintel_token');
}

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // If unauthorized and not already on login page, redirect to login
    if (!window.location.pathname.includes('/login')) {
      removeAuthToken();
      window.location.href = '/login';
    }
  }

  if (!response.ok) {
    let errorDetail = `Request failed: HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errorDetail;
    } catch {
      // Non-JSON error payload
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

// ----------------------------------------------------------------------
// Specific Typed API Calls
// ----------------------------------------------------------------------

export const api = {
  // Auth
  login: (formData: URLSearchParams) =>
    fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Login failed');
      }
      return res.json();
    }),

  getMe: () => apiRequest<any>('/auth/me'),

  // Dashboard
  getDashboardSummary: () => apiRequest<any>('/dashboard/summary'),

  // Intersections
  getIntersections: () => apiRequest<any[]>('/intersections'),
  getIntersection: (id: string) => apiRequest<any>(`/intersections/${id}`),
  createIntersection: (data: any) =>
    apiRequest<any>('/intersections', { method: 'POST', body: JSON.stringify(data) }),
  getIntersectionTraffic: (id: string) => apiRequest<any>(`/intersections/${id}/traffic`),
  getIntersectionWeather: (id: string) => apiRequest<any>(`/intersections/${id}/weather`),

  // Signals
  getControllers: () => apiRequest<any[]>('/signals/controllers'),
  createController: (data: any) =>
    apiRequest<any>('/signals/controllers', { method: 'POST', body: JSON.stringify(data) }),
  testControllerConnection: (id: string) =>
    apiRequest<any>(`/signals/controllers/${id}/test-connection`, { method: 'POST' }),
  issueSignalCommand: (data: any) =>
    apiRequest<any>('/signals/commands', { method: 'POST', body: JSON.stringify(data) }),

  // Cameras & Sensors
  getCameras: () => apiRequest<any[]>('/cameras'),
  createCamera: (data: any) =>
    apiRequest<any>('/cameras', { method: 'POST', body: JSON.stringify(data) }),
  testCameraConnection: (id: string) =>
    apiRequest<any>(`/cameras/${id}/test-connection`, { method: 'POST' }),

  getSensors: () => apiRequest<any[]>('/sensors'),
  createSensor: (data: any) =>
    apiRequest<any>('/sensors', { method: 'POST', body: JSON.stringify(data) }),

  // Incidents
  getIncidents: (statusFilter?: string) =>
    apiRequest<any[]>(`/incidents${statusFilter ? `?status_filter=${statusFilter}` : ''}`),
  createIncident: (data: any) =>
    apiRequest<any>('/incidents', { method: 'POST', body: JSON.stringify(data) }),
  updateIncidentStatus: (id: string, data: any) =>
    apiRequest<any>(`/incidents/${id}/status`, { method: 'PATCH', body: JSON.stringify(data) }),

  // Priority & Transit
  getEmergencyEvents: () => apiRequest<any>('/emergency'),
  submitPreemption: (data: any) =>
    apiRequest<any>('/emergency', { method: 'POST', body: JSON.stringify(data) }),
  getTransitEvents: () => apiRequest<any>('/transit'),

  // Predictions & Analytics
  getAiModels: () => apiRequest<any>('/predictions/models'),
  getForecast: (intersectionId: string) =>
    apiRequest<any>(`/predictions/forecast/${intersectionId}`),
  getAnalyticsSummary: () => apiRequest<any>('/analytics/summary'),

  // Corridors
  getCorridors: () => apiRequest<any[]>('/corridors'),
  createCorridor: (data: any) =>
    apiRequest<any>('/corridors', { method: 'POST', body: JSON.stringify(data) }),

  // AI Copilot
  queryCopilot: (query: string, intersectionId?: string) =>
    apiRequest<any>('/copilot/query', {
      method: 'POST',
      body: JSON.stringify({ query, intersection_id: intersectionId }),
    }),

  // Hardware & Devices
  getDevices: () => apiRequest<any[]>('/devices'),
  registerDevice: (data: any) =>
    apiRequest<any>('/devices', { method: 'POST', body: JSON.stringify(data) }),
  pingDevice: (id: string) =>
    apiRequest<any>(`/devices/${id}/ping`, { method: 'POST' }),

  // Maintenance & Audit
  getMaintenanceEvents: () => apiRequest<any[]>('/maintenance'),
  createMaintenanceOrder: (data: any) =>
    apiRequest<any>('/maintenance', { method: 'POST', body: JSON.stringify(data) }),
  completeMaintenance: (id: string) =>
    apiRequest<any>(`/maintenance/${id}/complete`, { method: 'PATCH' }),

  getAuditLogs: (action?: string) =>
    apiRequest<any[]>(`/audit${action ? `?action=${action}` : ''}`),

  // Settings & Wizards
  getSystemStatus: () => apiRequest<any>('/settings/status'),
  testControllerWizard: (ip: string, port: number) =>
    apiRequest<any>(`/settings/test-controller-wizard?ip_address=${ip}&port=${port}`, { method: 'POST' }),
  testCameraWizard: (streamUrl: string) =>
    apiRequest<any>(`/settings/test-camera-wizard?stream_url=${encodeURIComponent(streamUrl)}`, { method: 'POST' }),

  // Users
  getUsers: () => apiRequest<any[]>('/users'),
  createUser: (data: any) =>
    apiRequest<any>('/users', { method: 'POST', body: JSON.stringify(data) }),
};
