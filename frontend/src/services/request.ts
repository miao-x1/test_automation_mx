import axios from 'axios';
import { clearUser, refreshToken } from './auth';

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  // 不设置默认Content-Type，让axios根据数据类型自动判断
  // FormData → multipart/form-data (自动带boundary)
  // 普通对象 → application/json
  headers: {
    'X-Requested-With': 'XMLHttpRequest',
  },
  withCredentials: true, // 携带Cookie（httpOnly Cookie认证）
});

// 请求拦截器 - 自动携带Authorization头
request.interceptors.request.use(
  (config) => {
    console.log('[Request]', config.method?.toUpperCase(), (config.baseURL || '') + (config.url || ''));
    // 当发送FormData时，删除Content-Type让浏览器自动设置boundary
    if (config.data instanceof FormData) {
      if (config.headers && typeof config.headers.delete === 'function') {
        config.headers.delete('Content-Type');
      } else {
        delete config.headers['Content-Type'];
        delete config.headers['content-type'];
      }
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 是否正在刷新Token
let isRefreshing = false;
// 等待Token刷新的请求队列
let refreshSubscribers: Array<(token: string) => void> = [];

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

// 响应拦截器 - 处理401自动刷新Token
request.interceptors.response.use(
  (response) => {
    console.log('[Response]', response.config.url, response.data?.code, response.data?.message);
    return response.data;
  },
  async (error) => {
    console.error('[Response Error]', error.config?.url, error.response?.status, error.response?.data);
    const originalRequest = error.config;

    // 401未授权 - 尝试刷新Token
    if (error.response?.status === 401 && !originalRequest._retry) {
      // 认证接口的401不需要刷新
      if (originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/register')) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // 正在刷新，排队等待
        return new Promise((resolve) => {
          addRefreshSubscriber((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(request(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const newToken = await refreshToken();
        if (newToken) {
          onTokenRefreshed(newToken);
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return request(originalRequest);
        } else {
          // 刷新失败，清除登录状态，跳转登录页
          clearUser();
          window.location.href = '/auth/login';
          return Promise.reject(error);
        }
      } catch {
        clearUser();
        window.location.href = '/auth/login';
        return Promise.reject(error);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default request;
