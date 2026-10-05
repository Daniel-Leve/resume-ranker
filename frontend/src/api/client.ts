const DEFAULT_API_BASE_URL = "https://vxbiq8rt27.execute-api.ap-south-1.amazonaws.com/dev";

export function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl) return envUrl;
  return localStorage.getItem("VITE_API_BASE_URL") || DEFAULT_API_BASE_URL;
}

export function setApiBaseUrl(url: string): void {
  if (url) {
    localStorage.setItem("VITE_API_BASE_URL", url.trim().replace(/\/+$/, ""));
  } else {
    localStorage.removeItem("VITE_API_BASE_URL");
  }
}

export function isMockMode(): boolean {
  const envMock = import.meta.env.VITE_USE_MOCK_API;
  if (envMock !== undefined) return envMock === "true" || envMock === true;
  return localStorage.getItem("VITE_USE_MOCK_API") === "true";
}

export function setMockMode(enabled: boolean): void {
  localStorage.setItem("VITE_USE_MOCK_API", enabled ? "true" : "false");
}

export async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint}`;

  const defaultHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const response = await fetch(url, {
    ...options,
    headers: { ...defaultHeaders, ...options.headers },
  });

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson.error) errorMessage = errorJson.error;
    } catch {
      // JSON parsing failed, keep default error message
    }
    const err = new Error(errorMessage);
    (err as any).status = response.status;
    throw err;
  }

  return await response.json() as T;
}
