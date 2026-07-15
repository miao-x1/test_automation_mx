/**
 * DegradationAlert - 脚本降级警告组件
 *
 * 当脚本生成发生降级时，向用户显示警告提示：
 * - 降级级别（0=复用, 1-4=生成降级）
 * - 质量评估
 * - 建议操作
 * - 降级原因
 *
 * 使用场景：
 *   1. AgentRuntimePage — 管道执行结果
 *   2. RequirementInputPage — 需求生成结果
 *   3. 任何展示脚本生成结果的页面
 */
import { Alert, Tag, Space, Typography } from 'antd';
import {
  CheckCircleOutlined,
  WarningOutlined,
  ExclamationCircleOutlined,
  EditOutlined,
} from '@ant-design/icons';

const { Text, Link } = Typography;

export interface DegradationInfo {
  level: number;
  source: string;
  quality: 'high' | 'medium' | 'low';
  action_required: boolean;
  message: string;
}

interface DegradationAlertProps {
  info: DegradationInfo | null | undefined;
  /** 是否展开详情，默认根据 level 自动判断 */
  defaultExpanded?: boolean;
  /** 脚本内容引用（用于"去修改"按钮跳转） */
  scriptId?: number;
  onEdit?: () => void;
}

/** 降级级别配置 */
const LEVEL_CONFIG: Record<
  number,
  { label: string; color: string; icon: React.ReactNode; description: string }
> = {
  0: {
    label: '复用历史脚本',
    color: 'success',
    icon: <CheckCircleOutlined />,
    description: '该脚本来自历史复用，无需重新生成',
  },
  1: {
    label: '增强生成（策略模式）',
    color: 'success',
    icon: <CheckCircleOutlined />,
    description: '使用 StrategyAgent + PromptBuilder 生成，质量最高',
  },
  2: {
    label: '多页面流程生成',
    color: 'processing',
    icon: <WarningOutlined />,
    description: '增强生成器失败，已降级为 FlowScriptGenerator 跨页面生成',
  },
  3: {
    label: 'RAG增强生成',
    color: 'warning',
    icon: <WarningOutlined />,
    description: '已降级为标准 RAG+LLM 生成，建议审查脚本逻辑',
  },
  4: {
    label: '模板拼接（最低质量）',
    color: 'error',
    icon: <ExclamationCircleOutlined />,
    description: 'LLM生成全部失败，已使用模板拼接，必须人工修改后才能使用',
  },
};

/** 质量标签配置 */
const QUALITY_CONFIG: Record<string, { color: string; text: string }> = {
  high: { color: 'green', text: '高质量' },
  medium: { color: 'orange', text: '中等质量' },
  low: { color: 'red', text: '低质量' },
};

const DegradationAlert: React.FC<DegradationAlertProps> = ({
  info,
  defaultExpanded,
  onEdit,
}) => {
  if (!info) return null;

  const config = LEVEL_CONFIG[info.level] || LEVEL_CONFIG[4];
  const qualityConfig = QUALITY_CONFIG[info.quality] || QUALITY_CONFIG.medium;
  const showExpanded = defaultExpanded ?? info.level >= 3;

  // 级别0-1：无需提示
  if (info.level <= 1 && !info.action_required) {
    return null;
  }

  return (
    <Alert
      type={
        info.level >= 4 ? 'error' : info.level >= 3 ? 'warning' : info.level >= 2 ? 'info' : 'success'
      }
      showIcon
      icon={config.icon}
      message={
        <Space size="small">
          <Text strong>{config.label}</Text>
          <Tag color={config.color}>{`Level ${info.level}`}</Tag>
          <Tag color={qualityConfig.color}>{qualityConfig.text}</Tag>
          {info.action_required && (
            <Tag color="red" icon={<EditOutlined />}>
              需人工审查
            </Tag>
          )}
        </Space>
      }
      description={
        <div>
          <p style={{ margin: '4px 0' }}>{info.message || config.description}</p>
          {showExpanded && (
            <div style={{ marginTop: 8 }}>
              <p style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12, marginBottom: 4 }}>
                {config.description}
              </p>
              {info.action_required && (
                <Space>
                  <Text type="danger" style={{ fontSize: 13 }}>
                    ⚠ 此脚本可能无法直接运行，请检查后使用
                  </Text>
                  {onEdit && (
                    <Link
                      onClick={onEdit}
                      style={{ fontSize: 13 }}
                    >
                      去审查/修改脚本 →
                    </Link>
                  )}
                </Space>
              )}
            </div>
          )}
        </div>
      }
      style={{ marginBottom: 16 }}
    />
  );
};

export default DegradationAlert;
