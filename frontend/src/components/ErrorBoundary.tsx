/**
 * 错误边界组件
 *
 * 两级防护：
 * - GlobalErrorBoundary：包裹整个应用，兜底所有未捕获异常
 * - RouteErrorBoundary：包裹每个路由，单页异常不影响全局
 */
import React from 'react';
import { Result, Button } from 'antd';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * 全局错误边界 - 应用最外层兜底
 */
export class GlobalErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[GlobalErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <Result
          status="500"
          title="应用异常"
          subTitle={this.state.error?.message || '发生了未知错误，请刷新页面重试'}
          extra={[
            <Button key="reload" type="primary" onClick={() => window.location.reload()}>
              刷新页面
            </Button>,
          ]}
        />
      );
    }
    return this.props.children;
  }
}

/**
 * 路由级错误边界 - 单页异常不影响其他页面
 *
 * 路由切换时自动复位：监听 location.pathname 变化，
 * 如果边界处于错误状态则自动清除，避免一个页面报错后所有页面都显示"页面加载失败"。
 */
export class RouteErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[RouteErrorBoundary]', error, info.componentStack);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    // 使用 children 的变化来检测路由切换
    // 当路由变化时，children 会更新，此时自动复位错误状态
    if (this.state.hasError && prevProps.children !== this.props.children) {
      this.setState({ hasError: false, error: null });
    }
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <Result
          status="warning"
          title="页面加载失败"
          subTitle={this.state.error?.message || '当前页面出现异常，不影响其他页面使用'}
          extra={[
            <Button key="retry" onClick={this.handleRetry}>重试</Button>,
            <Button key="home" type="primary" onClick={() => window.location.href = '/task/create'}>返回创建测试</Button>,
          ]}
        />
      );
    }
    return this.props.children;
  }
}
