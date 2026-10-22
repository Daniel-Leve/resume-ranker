export interface AuthTokens {
  idToken: string;
  accessToken: string;
  refreshToken?: string;
}

export interface AuthUser {
  id: string;
  email: string;
  name?: string;
  tenantId?: string;
  groups?: string[];
}

const REGION = import.meta.env.VITE_COGNITO_REGION || "ap-south-1";
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || "7cu49634tijn7m70lhekvhuknj";
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;

const TOKEN_KEY_ID = "recruitai_id_token";
const TOKEN_KEY_ACCESS = "recruitai_access_token";
const TOKEN_KEY_REFRESH = "recruitai_refresh_token";
const USER_KEY = "recruitai_auth_user";

function parseJwt(token: string): Record<string, any> | null {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch (err) {
    console.error("Failed to parse JWT:", err);
    return null;
  }
}

async function cognitoRequest(target: string, payload: Record<string, any>) {
  const response = await fetch(COGNITO_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message = data.message || data.__type || "Authentication request failed";
    throw new Error(message);
  }

  return data;
}

export function saveTokens(tokens: AuthTokens) {
  if (tokens.idToken) localStorage.setItem(TOKEN_KEY_ID, tokens.idToken);
  if (tokens.accessToken) localStorage.setItem(TOKEN_KEY_ACCESS, tokens.accessToken);
  if (tokens.refreshToken) localStorage.setItem(TOKEN_KEY_REFRESH, tokens.refreshToken);

  const payload = parseJwt(tokens.idToken);
  if (payload) {
    const user: AuthUser = {
      id: payload.sub || "",
      email: payload.email || payload["cognito:username"] || "",
      name: payload.name || payload.given_name || payload.email?.split("@")[0] || "Recruiter",
      tenantId: payload["custom:tenant_id"] || payload["tenant_id"] || "",
      groups: payload["cognito:groups"] || [],
    };
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  }
  return null;
}

export function getIdToken(): string | null {
  return localStorage.getItem(TOKEN_KEY_ID);
}

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY_ACCESS);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(TOKEN_KEY_REFRESH);
}

export function getCurrentUser(): AuthUser | null {
  const userJson = localStorage.getItem(USER_KEY);
  if (userJson) {
    try {
      return JSON.parse(userJson);
    } catch {
      return null;
    }
  }
  const idToken = getIdToken();
  if (idToken) {
    const payload = parseJwt(idToken);
    if (payload && payload.exp * 1000 > Date.now()) {
      return {
        id: payload.sub || "",
        email: payload.email || payload["cognito:username"] || "",
        name: payload.name || payload.given_name || payload.email?.split("@")[0] || "Recruiter",
        tenantId: payload["custom:tenant_id"] || payload["tenant_id"] || "",
        groups: payload["cognito:groups"] || [],
      };
    }
  }
  return null;
}

export function isTokenValid(): boolean {
  const idToken = getIdToken();
  if (!idToken) return false;
  const payload = parseJwt(idToken);
  if (!payload || !payload.exp) return false;
  return payload.exp * 1000 > Date.now();
}

export async function signIn(email: string, password: string): Promise<AuthUser> {
  const result = await cognitoRequest("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: CLIENT_ID,
    AuthParameters: {
      USERNAME: email,
      PASSWORD: password,
    },
  });

  if (result.ChallengeName) {
    throw new Error(`Cognito challenge encountered: ${result.ChallengeName}. Only password auth is currently supported.`);
  }

  const authResult = result.AuthenticationResult;
  if (!authResult || !authResult.IdToken) {
    throw new Error("Invalid response from authentication server");
  }

  const user = saveTokens({
    idToken: authResult.IdToken,
    accessToken: authResult.AccessToken,
    refreshToken: authResult.RefreshToken,
  });

  if (!user) {
    throw new Error("Failed to extract user session");
  }

  return user;
}

export async function signUp(email: string, password: string, name: string) {
  return await cognitoRequest("SignUp", {
    ClientId: CLIENT_ID,
    Username: email,
    Password: password,
    UserAttributes: [
      { Name: "email", Value: email },
      { Name: "name", Value: name },
    ],
  });
}

export async function confirmSignUp(email: string, code: string) {
  return await cognitoRequest("ConfirmSignUp", {
    ClientId: CLIENT_ID,
    Username: email,
    ConfirmationCode: code,
  });
}

export async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    signOut();
    return false;
  }

  try {
    const result = await cognitoRequest("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      ClientId: CLIENT_ID,
      AuthParameters: {
        REFRESH_TOKEN: refreshToken,
      },
    });

    const authResult = result.AuthenticationResult;
    if (authResult?.IdToken && authResult?.AccessToken) {
      saveTokens({
        idToken: authResult.IdToken,
        accessToken: authResult.AccessToken,
        refreshToken: refreshToken,
      });
      return true;
    }
    return false;
  } catch (error) {
    console.error("Token refresh failed:", error);
    signOut();
    return false;
  }
}

export function signOut() {
  localStorage.removeItem(TOKEN_KEY_ID);
  localStorage.removeItem(TOKEN_KEY_ACCESS);
  localStorage.removeItem(TOKEN_KEY_REFRESH);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem("recruitai_tenant_id");
}
