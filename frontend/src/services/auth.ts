/**
 * 认证服务 - 登录/注册/Token管理
 *
 * Token存储策略：httpOnly Cookie（由后端设置）
 * 前端仅保存用户信息到sessionStorage（非敏感信息）
 */
import request from './request';

export interface LoginRequest {
  username: string;
  password: string;
  captcha_id: string;
  captcha_code: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  phone: string;
  sms_code: string;
  captcha_id: string;
  captcha_code: string;
  email?: string;
  display_name?: string;
}

export interface CaptchaPayload {
  captcha_id: string;
  image: string;
  expires_in: number;
  debug_text?: string;
}

export interface PublicAuthConfig {
  allow_register: boolean;
  register_require_approval: boolean;
  captcha_required: boolean;
  sms_provider: string;
  sms_echo: boolean;
}

export interface UserInfo {
  id: number;
  username: string;
  email?: string;
  display_name?: string;
  avatar?: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: UserInfo;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

const USER_KEY = 'test_automation_user';

/**
 * 登录页公开配置（无需登录）
 */
export async function getPublicAuthConfig(): Promise<PublicAuthConfig> {
  const res: any = await request.get('/auth/public-config');
  if (res.code === 200 && res.data) {
    return res.data;
  }
  return {
    allow_register: false,
    register_require_approval: false,
    captcha_required: true,
    sms_provider: 'console',
    sms_echo: false,
  };
}

export async function getCaptcha(): Promise<CaptchaPayload> {
  const res: any = await request.get('/auth/captcha');
  if (res.code === 200 && res.data) {
    return res.data;
  }
  throw new Error(res.message || '获取验证码失败');
}

export async function sendSmsCode(data: {
  phone: string;
  purpose: 'register' | 'reset';
  captcha_id: string;
  captcha_code: string;
}): Promise<{ sent: boolean; ttl: number; debug_code?: string }> {
  const res: any = await request.post('/auth/sms/send', data);
  if (res.code === 200 && res.data) {
    return res.data;
  }
  throw new Error(res.message || res.detail || '发送验证码失败');
}

export async function resetPassword(data: {
  phone: string;
  sms_code: string;
  new_password: string;
  captcha_id: string;
  captcha_code: string;
}): Promise<void> {
  const res: any = await request.post('/auth/password/reset', data);
  if (res.code === 200) {
    return;
  }
  throw new Error(res.message || res.detail || '重置密码失败');
}

/**
 * 用户注册
 */
export async function register(data: RegisterRequest): Promise<AuthResponse & { pending_approval?: boolean }> {
  const res: any = await request.post('/auth/register', data);
  if (res.code === 200 && res.data) {
    if (!res.data.pending_approval && res.data.user) {
      saveUser(res.data.user);
    }
    return res.data;
  }
  throw new Error(res.message || '注册失败');
}

/**
 * 用户登录
 */
export async function login(data: LoginRequest): Promise<AuthResponse> {
  const res: any = await request.post('/auth/login', data);
  if (res.code === 200 && res.data) {
    saveUser(res.data.user);
    return res.data;
  }
  throw new Error(res.message || '登录失败');
}

/**
 * 刷新Token
 */
export async function refreshToken(): Promise<string | null> {
  try {
    const res: any = await request.post('/auth/refresh');
    if (res.code === 200 && res.data?.access_token) {
      return res.data.access_token;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 获取当前用户信息
 */
export async function getCurrentUser(): Promise<UserInfo | null> {
  try {
    const res: any = await request.get('/auth/me');
    if (res.code === 200 && res.data) {
      saveUser(res.data);
      return res.data;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 退出登录
 */
export async function logout(): Promise<void> {
  try {
    await request.post('/auth/logout');
  } catch {
    // 忽略退出请求错误
  } finally {
    clearUser();
  }
}

/**
 * 保存用户信息到sessionStorage
 */
export function saveUser(user: UserInfo): void {
  try {
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // ignore
  }
}

/**
 * 获取本地缓存的用户信息
 */
export function getStoredUser(): UserInfo | null {
  try {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * 清除用户信息
 */
export function clearUser(): void {
  sessionStorage.removeItem(USER_KEY);
}

/**
 * 检查是否已登录
 */
export function isAuthenticated(): boolean {
  return getStoredUser() !== null;
}
