/**
 * AI识别结果卡片
 *
 * 展示AI智能识别的测试类型结果：
 *   "AI判断该需求为Web自动化测试，准确率96%"
 *
 * 用户可以修改识别结果。
 */
import { useState, useEffect } from 'react';
import {
  Card, Tag, Progress, Select, Space, Typography, Button, Spin, Alert, Descriptions, Tooltip,
} from 'antd';
import {
  RobotOutlined, EditOutlined, CheckOutlined, CloseOutlined, ReloadOutlined,
} from '@ant-design/icons';
import {
  type ClassifyResult,
  TEST_TYPE_LABELS, TEST_TYPE_COLORS, TEST_TYPE_ICONS,
  PLATFORM_LABELS, FRAMEWORK_LABELS,
  formatClassificationText,
} from '../services/testTypeClassifier';

const { Text } = Typography;

export interface AIClassifyCardProps {
  /** AI识别结果 */
  result: ClassifyResult | null;
  /** 是否正在识别中 */
  loading: boolean;
  /** 识别错误信息 */
  error: string | null;
  /** 用户修改后的类型回调 */
  onChange?: (testType: string, framework: string, platform: string) => void;
  /** 重新识别回调 */
  onReclassify?: () => void;
}

const TEST_TYPE_OPTIONS = [
  { value: 'web', label: '🌐 Web自动化测试' },
  { value: 'api', label: '🔌 API接口测试' },
  { value: 'android', label: '📱 Android移动端测试' },
  { value: 'performance', label: '⚡ 性能测试' },
];

const FRAMEWORK_OPTIONS: Record<string, { value: string; label: string }[]> = {
  web: [{ value: 'playwright', label: 'Playwright' }],
  api: [{ value: 'pytest', label: 'Pytest' }, { value: 'requests', label: 'Requests' }],
  android: [{ value: 'appium', label: 'Appium' }],
  performance: [{ value: 'jmeter', label: 'JMeter' }, { value: 'locust', label: 'Locust' }],
};

export default function AIClassifyCard({
  result,
  loading,
  error,
  onChange,
  onReclassify,
}: AIClassifyCardProps) {
  const [editing, setEditing] = useState(false);
  const [editType, setEditType] = useState<string>('');
  const [editFramework, setEditFramework] = useState<string>('');
  const [editPlatform, setEditPlatform] = useState<string>('');

  useEffect(() => {
    if (result) {
      setEditType(result.test_type);
      setEditFramework(result.framework);
      setEditPlatform(result.platform);
    }
  }, [result]);

  const handleSaveEdit = () => {
    onChange?.(editType, editFramework, editPlatform);
    setEditing(false);
  };

  const handleCancelEdit = () => {
    if (result) {
      setEditType(result.test_type);
      setEditFramework(result.framework);
      setEditPlatform(result.platform);
    }
    setEditing(false);
  };

  // 加载中
  if (loading) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <Spin tip="AI正在分析需求..." />
        </div>
      </Card>
    );
  }

  // 错误状态
  if (error) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <Alert
          message="AI识别失败"
          description={error}
          type="warning"
          showIcon
          action={
            onReclassify && (
              <Button size="small" onClick={onReclassify} icon={<ReloadOutlined />}>
                重试
              </Button>
            )
          }
        />
      </Card>
    );
  }

  // 无结果
  if (!result) {
    return null;
  }

  const confidencePercent = Math.round(result.confidence * 100);
  const typeColor = TEST_TYPE_COLORS[result.test_type] || 'default';
  const typeIcon = TEST_TYPE_ICONS[result.test_type] || '?';

  return (
    <Card
      size="small"
      style={{
        marginBottom: 16,
        border: `1px solid ${typeColor === 'default' ? '#d9d9d9' : typeColor}`,
        background: 'linear-gradient(135deg, #fafafa 0%, #f0f5ff 100%)',
      }}
      title={
        <Space>
          <RobotOutlined style={{ color: '#1677ff' }} />
          <span style={{ fontWeight: 600 }}>AI智能识别结果</span>
        </Space>
      }
      extra={
        !editing && (
          <Space>
            <Tooltip title="重新识别">
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                onClick={onReclassify}
              />
            </Tooltip>
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              onClick={() => setEditing(true)}
            >
              修改
            </Button>
          </Space>
        )
      }
    >
      {!editing ? (
        <>
          {/* 主要展示：AI判断该需求为XXX，准确率XX% */}
          <div style={{ marginBottom: 12 }}>
            <Space align="center" size="middle">
              <span style={{ fontSize: 28 }}>{typeIcon}</span>
              <div>
                <Text strong style={{ fontSize: 16 }}>
                  {formatClassificationText(result)}
                </Text>
                <div style={{ marginTop: 4 }}>
                  <Space size="small">
                    <Tag color={typeColor}>
                      {TEST_TYPE_LABELS[result.test_type]}
                    </Tag>
                    <Tag>{PLATFORM_LABELS[result.platform] || result.platform}</Tag>
                    <Tag color="blue">
                      {FRAMEWORK_LABELS[result.framework] || result.framework}
                    </Tag>
                  </Space>
                </div>
              </div>
            </Space>
          </div>

          {/* 置信度进度条 */}
          <div style={{ marginBottom: 8 }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>置信度</Text>
              <Text style={{ fontSize: 12, fontWeight: 600 }}>{confidencePercent}%</Text>
            </Space>
            <Progress
              percent={confidencePercent}
              size="small"
              status={confidencePercent >= 80 ? 'success' : confidencePercent >= 60 ? 'active' : 'exception'}
              strokeColor={confidencePercent >= 80 ? '#52c41a' : confidencePercent >= 60 ? '#1677ff' : '#faad14'}
            />
          </div>

          {/* 识别依据 */}
          {result.detected_signals && result.detected_signals.length > 0 && (
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>识别依据:</Text>
              <div style={{ marginTop: 4 }}>
                {result.detected_signals.map((signal, idx) => (
                  <Tag key={idx} style={{ marginBottom: 4, fontSize: 11 }}>
                    {signal}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* 原因说明 */}
          {result.reason && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{result.reason}</Text>
            </div>
          )}
        </>
      ) : (
        /* 编辑模式 */
        <div>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="测试类型">
              <Select
                value={editType}
                onChange={(val) => {
                  setEditType(val);
                  // 根据类型自动更新框架和平台
                  const typeFrameworkMap: Record<string, string> = {
                    web: 'playwright', api: 'pytest', android: 'appium', performance: 'jmeter',
                  };
                  const typePlatformMap: Record<string, string> = {
                    web: 'browser', api: 'server', android: 'mobile', performance: 'server',
                  };
                  setEditFramework(typeFrameworkMap[val] || '');
                  setEditPlatform(typePlatformMap[val] || '');
                }}
                options={TEST_TYPE_OPTIONS}
                style={{ width: '100%' }}
              />
            </Descriptions.Item>
            <Descriptions.Item label="测试平台">
              <Tag>{PLATFORM_LABELS[editPlatform] || editPlatform}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="测试框架">
              <Select
                value={editFramework}
                onChange={setEditFramework}
                options={FRAMEWORK_OPTIONS[editType] || []}
                style={{ width: '100%' }}
              />
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }}>
            <Button size="small" icon={<CloseOutlined />} onClick={handleCancelEdit}>
              取消
            </Button>
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={handleSaveEdit}>
              确认
            </Button>
          </Space>
        </div>
      )}
    </Card>
  );
}
