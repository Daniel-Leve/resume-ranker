import { apiRequest, isMockMode } from './client';
import { Tenant } from '../types';
import { MOCK_TENANT } from '../fixtures/mockData';

export async function createTenant(name: string): Promise<Tenant> {
  if (isMockMode()) {
    return {
      tenant_id: `tenant-${Date.now()}`,
      name,
      status: "ACTIVE",
      created_at: new Date().toISOString()
    };
  }
  return apiRequest<Tenant>("/tenants", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getDefaultTenant(): Tenant {
  return MOCK_TENANT;
}
