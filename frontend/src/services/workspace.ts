import request from './request';

export type OrgRole = 'OWNER' | 'ADMIN' | 'MEMBER';
export type ProjectRole = 'PROJECT_ADMIN' | 'TESTER' | 'REPORTER' | 'GUEST' | 'VIEWER';

export type Organization = {
  id: number;
  name: string;
  description?: string;
  owner_id: number;
  avatar?: string;
  is_personal?: boolean;
  member_count?: number;
  project_count?: number;
  my_role?: OrgRole | string;
};

export type Project = {
  id: number;
  name: string;
  description?: string;
  organization_id: number;
  organization_name?: string;
  is_default?: boolean;
  member_count?: number;
  last_test_at?: string | null;
  status?: string;
  success_rate?: number | null;
  job_count?: number;
};

export type Member = {
  id: number;
  username: string;
  display_name?: string;
  email?: string;
  avatar?: string;
  role: string;
  joined_at?: string;
};

export type OrgInvite = {
  id: number;
  email?: string;
  role: string;
  project_id?: number;
  project_role?: string;
  status: string;
  token?: string;
  invite_path?: string;
  expires_at?: string;
  created_at?: string;
};

const dataOf = (res: any) => res?.data ?? res;

export async function fetchWorkspace() {
  return dataOf(await request.get('/workspace'));
}

export async function createOrganization(name: string, description?: string, avatar?: string) {
  return dataOf(await request.post('/organizations', { name, description, avatar }));
}

export async function getOrganization(id: number) {
  return dataOf(await request.get(`/organizations/${id}`));
}

export async function updateOrganization(id: number, name: string, description?: string, avatar?: string) {
  return dataOf(await request.patch(`/organizations/${id}`, { name, description, avatar }));
}

export async function createProject(organizationId: number, name: string, description?: string) {
  return dataOf(await request.post('/projects', {
    organization_id: organizationId,
    name,
    description,
  }));
}

export async function getProject(id: number) {
  return dataOf(await request.get(`/projects/${id}`));
}

export async function updateProject(id: number, name: string, description?: string) {
  return dataOf(await request.patch(`/projects/${id}`, { name, description }));
}

export async function deleteProject(id: number) {
  return dataOf(await request.delete(`/projects/${id}`));
}

export async function addProjectMember(projectId: number, payload: { username?: string; email?: string; role: ProjectRole }) {
  return dataOf(await request.post(`/projects/${projectId}/members`, payload));
}

export async function updateProjectMember(projectId: number, userId: number, role: ProjectRole) {
  return dataOf(await request.patch(`/projects/${projectId}/members/${userId}`, { role }));
}

export async function removeProjectMember(projectId: number, userId: number) {
  return dataOf(await request.delete(`/projects/${projectId}/members/${userId}`));
}

export async function updateOrgMember(orgId: number, userId: number, role: OrgRole) {
  return dataOf(await request.patch(`/organizations/${orgId}/members/${userId}`, { role }));
}

export async function removeOrgMember(orgId: number, userId: number) {
  return dataOf(await request.delete(`/organizations/${orgId}/members/${userId}`));
}

export async function inviteMember(orgId: number, payload: {
  email?: string;
  role?: OrgRole;
  project_id?: number;
  project_role?: ProjectRole;
}) {
  return dataOf(await request.post(`/organizations/${orgId}/invites`, payload));
}

export async function acceptInvite(token: string) {
  return dataOf(await request.post('/invites/accept', { token }));
}

export async function declineInvite(token: string) {
  return dataOf(await request.post('/invites/decline', { token }));
}

export async function getInvite(token: string) {
  return dataOf(await request.get(`/invites/${token}`));
}

export async function listOrgInvites(orgId: number) {
  return dataOf(await request.get(`/organizations/${orgId}/invites`));
}

export async function cancelInvite(orgId: number, inviteId: number) {
  return dataOf(await request.delete(`/organizations/${orgId}/invites/${inviteId}`));
}

export async function listProjectJobs(projectId: number) {
  return dataOf(await request.get(`/projects/${projectId}/jobs`));
}

export async function listPipelines(projectId: number) {
  return dataOf(await request.get(`/projects/${projectId}/pipelines`));
}

export async function createPipeline(projectId: number, name: string, jobIds: number[], description?: string) {
  return dataOf(await request.post(`/projects/${projectId}/pipelines`, {
    name,
    job_ids: jobIds,
    description,
  }));
}

export async function runPipeline(projectId: number, pipelineId: number) {
  return dataOf(await request.post(`/projects/${projectId}/pipelines/${pipelineId}/run`));
}

export async function listProjectEnvs(projectId: number) {
  return dataOf(await request.get(`/projects/${projectId}/environments`));
}

export async function createProjectEnv(projectId: number, payload: {
  name: string;
  base_url?: string;
  account?: string;
  password?: string;
  description?: string;
}) {
  return dataOf(await request.post(`/projects/${projectId}/environments`, payload));
}
