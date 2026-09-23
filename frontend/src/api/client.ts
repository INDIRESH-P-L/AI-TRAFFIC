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

  // The camera and sensor create endpoints take query parameters, not a body.
  createCameraQuery: (query: string) =>
    apiRequest<any>(`/cameras?${query}`, { method: 'POST' }),

  getSensors: () => apiRequest<any[]>('/sensors'),
  createSensorQuery: (query: string) =>
    apiRequest<any>(`/sensors?${query}`, { method: 'POST' }),
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

  // GIS map layers (every feature carries provenance)
  getMapLayers: (include?: string[]) =>
    apiRequest<any>(`/map${include && include.length ? `?include=${include.join(',')}` : ''}`),

  // Junction timeline & historical replay
  getJunctionTimeline: (id: string, hours = 24, limit = 50) =>
    apiRequest<any>(`/timeline/${id}?hours=${hours}&limit=${limit}`),
  getJunctionReplay: (id: string, minutes = 60) =>
    apiRequest<any>(`/timeline/${id}/replay?minutes=${minutes}`),

  // Guided signal command workflow: preview validates without writing anything
  validateSignalCommand: (data: any, refreshState = true) =>
    apiRequest<any>(`/signals/commands/validate?refresh_state=${refreshState}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ---- Phase 2: provider health & stream diagnostics ----
  getProviderHealth: () => apiRequest<any>('/health/providers'),
  getStreamHealth: () => apiRequest<any>('/health/stream'),
  getPollerStatus: () => apiRequest<any>('/health/poller'),
  pollNow: () => apiRequest<any>('/health/poller/poll-now', { method: 'POST' }),

  // ---- Phase 2: alert rules ----
  getRuleConditionTypes: () => apiRequest<any>('/rules/condition-types'),
  getRules: () => apiRequest<any[]>('/rules'),
  createRule: (data: any) =>
    apiRequest<any>('/rules', { method: 'POST', body: JSON.stringify(data) }),
  updateRule: (id: string, data: any) =>
    apiRequest<any>(`/rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRule: (id: string) => apiRequest<any>(`/rules/${id}`, { method: 'DELETE' }),
  evaluateRule: (id: string, dryRun = true) =>
    apiRequest<any>(`/rules/${id}/evaluate?dry_run=${dryRun}`, { method: 'POST' }),
  getRuleEvaluations: (id: string) => apiRequest<any>(`/rules/${id}/evaluations`),
  getAlertDeliveries: (alertId: string) =>
    apiRequest<any>(`/rules/alerts/${alertId}/deliveries`),
  acknowledgeAlert: (alertId: string) =>
    apiRequest<any>(`/rules/alerts/${alertId}/acknowledge`, { method: 'POST' }),

  // ---- Phase 2: performance analytics ----
  getPerformanceReport: (id: string, hours = 24) =>
    apiRequest<any>(`/analytics/performance/${id}?hours=${hours}`),
  getTimeOfDayProfile: (id: string, days = 7) =>
    apiRequest<any>(`/analytics/time-of-day/${id}?days=${days}`),

  // ---- Phase 2: optimiser & scenario sandbox ----
  recommendTiming: (data: any) =>
    apiRequest<any>('/optimizer/recommend', { method: 'POST', body: JSON.stringify(data) }),
  getRecommendations: (id: string) =>
    apiRequest<any>(`/optimizer/recommendations/${id}`),
  runScenario: (data: any) =>
    apiRequest<any>('/scenario/run', { method: 'POST', body: JSON.stringify(data) }),
  getScenarioTemplate: (controllerId: string) =>
    apiRequest<any>(`/scenario/template/${controllerId}`),
  getScenarioRuns: (intersectionId?: string) =>
    apiRequest<any>(`/scenario/runs${intersectionId ? `?intersection_id=${intersectionId}` : ''}`),

  // ---- Phase 2: governance ----
  getScopes: () => apiRequest<any>('/governance/scopes'),
  exploreAudit: (params: string) => apiRequest<any>(`/governance/audit?${params}`),
  verifyAuditChain: () => apiRequest<any>('/governance/audit/verify'),
  getApiKeys: () => apiRequest<any>('/governance/api-keys'),
  createApiKey: (data: any) =>
    apiRequest<any>('/governance/api-keys', { method: 'POST', body: JSON.stringify(data) }),
  revokeApiKey: (id: string) =>
    apiRequest<any>(`/governance/api-keys/${id}`, { method: 'DELETE' }),

  // ---- Phase 2: incident lifecycle ----
  acknowledgeIncident: (id: string) =>
    apiRequest<any>(`/incidents/${id}/acknowledge`, { method: 'POST' }),
  assignIncident: (id: string, assignee: string) =>
    apiRequest<any>(`/incidents/${id}/assign?assignee=${encodeURIComponent(assignee)}`, {
      method: 'POST',
    }),
  getIncidentSla: (id: string) => apiRequest<any>(`/incidents/${id}/sla`),
  getIncidentTimeline: (id: string) => apiRequest<any>(`/incidents/${id}/timeline`),
  getIncidentEvidence: (id: string) => apiRequest<any>(`/incidents/${id}/evidence`),
  getIncidentReport: (id: string) => apiRequest<any>(`/incidents/${id}/report`),

  // ---- Phase 2: Copilot 2.0 ----
  askCopilot: (query: string, intersectionId?: string) =>
    apiRequest<any>('/copilot/ask', {
      method: 'POST',
      body: JSON.stringify({ query, intersection_id: intersectionId }),
    }),
  getCopilotTools: () => apiRequest<any>('/copilot/tools'),
  getCopilotSession: () => apiRequest<any>('/copilot/session'),
  clearCopilotSession: () => apiRequest<any>('/copilot/session', { method: 'DELETE' }),

  // ---- Phase 2: import & reporting ----
  getImportFormats: () => apiRequest<any>('/ingest/formats'),
  getReportCatalog: () => apiRequest<any>('/reports/catalog'),
  getDailyReport: () => apiRequest<any>('/reports/daily-operations'),

  // ---- Phase 3: data-quality trust score ----
  getNetworkTrust: (windowMinutes = 60) =>
    apiRequest<any>(`/trust/network?window_minutes=${windowMinutes}`),
  getJunctionTrust: (id: string, windowMinutes = 60) =>
    apiRequest<any>(`/trust/${id}?window_minutes=${windowMinutes}`),

  // ---- Phase 3: post-change verification ----
  verifyCommand: (commandId: string, windowMinutes = 30) =>
    apiRequest<any>(`/verification/command/${commandId}?window_minutes=${windowMinutes}`),
  getRecentVerifications: (intersectionId?: string, limit = 10) =>
    apiRequest<any>(
      `/verification/recent?limit=${limit}` +
        (intersectionId ? `&intersection_id=${intersectionId}` : ''),
    ),
  // `changed_at` is URI-encoded because an ISO timestamp carries a "+00:00"
  // offset and a bare "+" in a query string decodes as a space.
  verifyWindow: (id: string, changedAt: string, windowMinutes = 30, settleMinutes = 2) =>
    apiRequest<any>(
      `/verification/window/${id}?changed_at=${encodeURIComponent(changedAt)}` +
        `&window_minutes=${windowMinutes}&settle_minutes=${settleMinutes}`,
    ),

  // ---- Phase 3: corridor stringline ----
  getStringline: (corridorId: string, minutes = 15, phases?: string) =>
    apiRequest<any>(
      `/stringline/${corridorId}?minutes=${minutes}` +
        (phases ? `&phases=${encodeURIComponent(phases)}` : ''),
    ),

  // ---- Phase 3: shift handover ----
  getHandovers: (limit = 20) => apiRequest<any>(`/handover?limit=${limit}`),
  previewHandover: (shiftHours = 8) =>
    apiRequest<any>(`/handover/preview?shift_hours=${shiftHours}`),
  createHandover: (data: any) =>
    apiRequest<any>('/handover', { method: 'POST', body: JSON.stringify(data) }),
  getHandover: (id: string) => apiRequest<any>(`/handover/${id}`),
  updateHandover: (id: string, data: any) =>
    apiRequest<any>(`/handover/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  signOffHandover: (id: string) =>
    apiRequest<any>(`/handover/${id}/sign-off`, { method: 'POST' }),
  acknowledgeHandover: (id: string) =>
    apiRequest<any>(`/handover/${id}/acknowledge`, { method: 'POST' }),

  // Users
  getUsers: () => apiRequest<any[]>('/users'),
  createUser: (data: any) =>
    apiRequest<any>('/users', { method: 'POST', body: JSON.stringify(data) }),
};
