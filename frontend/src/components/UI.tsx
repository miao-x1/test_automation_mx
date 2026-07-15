/**
 * 统一UI组件库
 *
 * StatusTag  - 统一状态标签（颜色语义一致）
 * PageHeader - 统一页面头部（标题 + 状态 + 操作）
 * EmptyGuide - 统一空状态引导
 */
import React from 'react';
import { Tag, Typography, Space, Button, Empty } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Text, Title: AntTitle } = Typography;

// ==================== StatusTag ====================

const STATUS_CONFIG: Record<string, { color: string; label: string; dotColor: string }> = {
  pending:            { color: 'default',    label: '待处理',   dotColor: '#d9d9d9' },
  processing:         { color: 'processing', label: '处理中',   dotColor: '#1890ff' },
  running:            { color: 'processing', label: '执行中',   dotColor: '#1890ff' },
  analyzing:          { color: 'processing', label: '分析中',   dotColor: '#722ed1' },
  generating_case:    { color: 'processing', label: '生成用例', dotColor: '#fa8c16' },
  generating_script:  { color: 'processing', label: '生成脚本', dotColor: '#13c2c2' },
  success:            { color: 'success',    label: '成功',     dotColor: '#52c41a' },
  completed:          { color: 'success',    label: '已完成',   dotColor: '#52c41a' },
  failed:             { color: 'error',      label: '失败',     dotColor: '#ff4d4f' },
};

export function StatusTag({ status, size = 'default' }: { status: string; size?: 'small' | 'default' }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  return (
    <Tag color={cfg.color} style={size === 'small' ? { fontSize: 11, lineHeight: '18px', padding: '0 4px' } : undefined}>
      <span style={{
        display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
        background: cfg.dotColor, marginRight: 6, verticalAlign: 'middle',
      }} />
      {cfg.label}
    </Tag>
  );
}

// ==================== PageHeader ====================

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  status?: string;
  actions?: React.ReactNode;
  backTo?: string;
}

export function PageHeader({ title, subtitle, icon, status, actions, backTo }: PageHeaderProps) {
  const navigate = useNavigate();
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '16px 0', borderBottom: '1px solid #f0f0f0', marginBottom: 16,
    }}>
      <Space size="middle" align="center">
        {backTo && (
          <Button type="text" icon={<ArrowRightOutlined rotate={180} />} onClick={() => navigate(backTo)} style={{ marginLeft: -8 }} />
        )}
        <div>
          <Space align="center" size="middle">
            {icon}
            <AntTitle level={4} style={{ margin: 0 }}>{title}</AntTitle>
            {status && <StatusTag status={status} />}
          </Space>
          {subtitle && <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 13 }}>{subtitle}</Text>}
        </div>
      </Space>
      {actions && <Space size="small">{actions}</Space>}
    </div>
  );
}

// ==================== EmptyGuide ====================

interface EmptyGuideProps {
  title: string;
  description: string;
  actionLabel: string;
  actionTo: string;
  icon?: React.ReactNode;
}

export function EmptyGuide({ title, description, actionLabel, actionTo, icon }: EmptyGuideProps) {
  const navigate = useNavigate();
  return (
    <div style={{ textAlign: 'center', padding: '48px 0' }}>
      <Empty
        image={icon || undefined}
        description={
          <div>
            <Text strong style={{ fontSize: 15, display: 'block', marginBottom: 4 }}>{title}</Text>
            <Text type="secondary">{description}</Text>
          </div>
        }
      >
        <Button type="primary" onClick={() => navigate(actionTo)}>
          {actionLabel} <ArrowRightOutlined />
        </Button>
      </Empty>
    </div>
  );
}

// ==================== Button Hierarchy ====================

/**
 * 按钮分级规则：
 * - 主操作（Primary）：每区域最多1个，如"开始执行""创建需求"
 * - 次操作（Default/Ghost）：如"刷新""下载""编辑"
 * - 危险操作（Danger）：如"删除"，需Popconfirm
 *
 * 使用示例：
 * <Space>
 *   <Button type="primary">开始执行</Button>           ← 主操作
 *   <Button icon={<ReloadOutlined />}>刷新</Button>     ← 次操作
 *   <Popconfirm><Button danger>删除</Button></Popconfirm> ← 危险操作
 * </Space>
 */
