/**
 * 脚本上传页面
 *
 * 流程：上传脚本 → 解析 → 预览 → 执行
 */
import { useState, useCallback } from 'react';
import {
  Card, Upload, Button, Space, Typography, Tag, Table, Alert, Steps,
  message, Descriptions, Divider, Input, InputNumber,
} from 'antd';
import {
  UploadOutlined, PlayCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, WarningOutlined, CodeOutlined, FileTextOutlined,
  EyeOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { uploadScript, parseScript, executeScript } from '../services/scriptUpload';
import type { ParsedScript, ValidationResult, ExecuteResult } from '../services/scriptUpload';
import { PageHeader } from '../components/UI';

const { TextArea } = Input;
const { Text } = Typography;

const TYPE_MAP: Record<string, { color: string; label: string }> = {
  playwright: { color: 'green', label: 'Playwright' },
  midscene: { color: 'purple', label: 'Midscene' },
  yaml: { color: 'blue', label: 'YAML' },
  json: { color: 'cyan', label: 'JSON' },
};

export default function ScriptUploadPage() {
  const [currentStep, setCurrentStep] = useState(0);
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('');
  const [parsed, setParsed] = useState<ParsedScript | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [execResult, setExecResult] = useState<ExecuteResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [timeout, setTimeout_] = useState(300);

  // 上传文件
  const handleUpload = useCallback(async (file: File) => {
    setLoading(true);
    setCurrentStep(1);
    try {
      const result = await uploadScript(file);
      setContent(result.content);
      setFilename(result.filename);
      setParsed(result.parsed);
      setValidation(result.validation);
      setCurrentStep(2);
      if (result.validation.valid) {
        message.success('脚本解析成功');
      } else {
        message.warning('脚本有校验问题，请检查');
      }
    } catch (e: any) {
      message.error(e?.message || '上传失败');
      setCurrentStep(0);
    }
    setLoading(false);
  }, []);

  // 粘贴内容解析
  const handleParse = useCallback(async () => {
    if (!content.trim()) {
      message.warning('请输入脚本内容');
      return;
    }
    setLoading(true);
    setCurrentStep(1);
    try {
      const result = await parseScript(content, filename);
      setParsed(result.parsed);
      setValidation(result.validation);
      setCurrentStep(2);
      if (result.validation.valid) {
        message.success('解析成功');
      } else {
        message.warning('脚本有校验问题');
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '解析失败');
      setCurrentStep(0);
    }
    setLoading(false);
  }, [content, filename]);

  // 执行
  const handleExecute = useCallback(async () => {
    if (!parsed || !validation?.valid) {
      message.error('脚本校验未通过，无法执行');
      return;
    }
    setLoading(true);
    setCurrentStep(3);
    try {
      const result = await executeScript({
        content,
        script_type: parsed.script_type,
        language: parsed.language,
        timeout,
      });
      setExecResult(result);
      setCurrentStep(4);
      if (result.success) {
        message.success('脚本执行成功');
      } else {
        message.error('脚本执行失败');
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '执行失败');
      setCurrentStep(2);
    }
    setLoading(false);
  }, [content, parsed, validation, timeout]);

  // 重置
  const handleReset = () => {
    setCurrentStep(0);
    setContent('');
    setFilename('');
    setParsed(null);
    setValidation(null);
    setExecResult(null);
  };

  // 步骤列
  const stepColumns: ColumnsType<Record<string, any>> = [
    { title: '#', dataIndex: 'step', width: 40 },
    { title: '动作', dataIndex: 'action', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '描述', dataIndex: 'name', ellipsis: true, render: (v: string, r: any) => v || r.description || r.raw?.slice(0, 60) || '-' },
    { title: '值', dataIndex: 'value', ellipsis: true, render: (v: string) => v || '-' },
  ];

  return (
    <div>
      <PageHeader
        title="脚本上传"
        icon={<UploadOutlined />}
        subtitle="上传测试脚本，自动解析校验后直接执行"
      />

      <Steps
        current={currentStep}
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          { title: '上传/输入', icon: <UploadOutlined /> },
          { title: '解析', icon: <EyeOutlined /> },
          { title: '预览', icon: <FileTextOutlined /> },
          { title: '执行', icon: <PlayCircleOutlined /> },
          { title: '结果', icon: <CheckCircleOutlined /> },
        ]}
      />

      {/* ===== Step 0: 上传/输入 ===== */}
      {currentStep === 0 && (
        <Card>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Upload
              accept=".py,.js,.ts,.mjs,.yaml,.yml,.json"
              maxCount={1}
              showUploadList={false}
              customRequest={({ file, onSuccess, onError }) => {
                handleUpload(file as File)
                  .then(() => onSuccess?.(null))
                  .catch((err) => onError?.(err));
              }}
            >
              <Button type="primary" icon={<UploadOutlined />} size="large" loading={loading}>
                上传脚本文件
              </Button>
            </Upload>

            <Divider plain>或直接粘贴脚本内容</Divider>

            <TextArea
              value={content}
              onChange={e => setContent(e.target.value)}
              placeholder="粘贴Playwright/Midscene/YAML/JSON脚本内容..."
              autoSize={{ minRows: 8, maxRows: 20 }}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button icon={<EyeOutlined />} onClick={handleParse} loading={loading} disabled={!content.trim()}>
                解析脚本
              </Button>
            </div>
          </Space>
        </Card>
      )}

      {/* ===== Step 2: 预览 ===== */}
      {currentStep >= 2 && parsed && (
        <Card
          title={<Space><CodeOutlined /> 脚本预览</Space>}
          extra={
            <Space>
              <Button size="small" onClick={handleReset}>重新上传</Button>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={handleExecute}
                loading={loading}
                disabled={!validation?.valid}
              >
                执行脚本
              </Button>
            </Space>
          }
        >
          {/* 校验结果 */}
          {validation && (
            <Alert
              type={validation.valid ? 'success' : 'error'}
              showIcon
              icon={validation.valid ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
              message={
                <Space>
                  <Text strong>{validation.valid ? '校验通过' : '校验失败'}</Text>
                  <Tag color={validation.score >= 0.7 ? 'green' : validation.score >= 0.4 ? 'orange' : 'red'}>
                    质量: {(validation.score * 100).toFixed(0)}%
                  </Tag>
                  {parsed.script_type && (
                    <Tag color={TYPE_MAP[parsed.script_type]?.color || 'default'}>
                      {TYPE_MAP[parsed.script_type]?.label || parsed.script_type}
                    </Tag>
                  )}
                </Space>
              }
              description={
                <>
                  {validation.errors.length > 0 && (
                    <div>{validation.errors.map((e, i) => <div key={i} style={{ color: 'red' }}><CloseCircleOutlined /> {e}</div>)}</div>
                  )}
                  {validation.warnings.length > 0 && (
                    <div>{validation.warnings.map((w, i) => <div key={i} style={{ color: 'orange' }}><WarningOutlined /> {w}</div>)}</div>
                  )}
                </>
              }
              style={{ marginBottom: 12 }}
            />
          )}

          {/* 脚本信息 */}
          <Descriptions size="small" bordered column={2} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="名称">{parsed.name || '-'}</Descriptions.Item>
            <Descriptions.Item label="类型">{TYPE_MAP[parsed.script_type]?.label || parsed.script_type}</Descriptions.Item>
            <Descriptions.Item label="语言">{parsed.language}</Descriptions.Item>
            <Descriptions.Item label="目标URL">{parsed.target_url || '-'}</Descriptions.Item>
            <Descriptions.Item label="函数">{parsed.functions.length > 0 ? parsed.functions.join(', ') : '-'}</Descriptions.Item>
            <Descriptions.Item label="步骤数">{parsed.steps.length}</Descriptions.Item>
          </Descriptions>

          {/* 步骤预览 */}
          {parsed.steps.length > 0 && (
            <>
              <Text strong style={{ marginBottom: 8, display: 'block' }}>步骤预览</Text>
              <Table
                columns={stepColumns}
                dataSource={parsed.steps}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                style={{ marginBottom: 12 }}
              />
            </>
          )}

          {/* 执行配置 */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 8 }}>
            <Text>超时时间:</Text>
            <InputNumber value={timeout} onChange={v => setTimeout_(v || 300)} min={30} max={3600} step={30} />
            <Text type="secondary">秒</Text>
          </div>

          {/* 原始脚本 */}
          <details style={{ marginTop: 12 }}>
            <summary><Text type="secondary">查看原始脚本</Text></summary>
            <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 300, overflow: 'auto', fontSize: 11, marginTop: 8 }}>
              {content}
            </pre>
          </details>
        </Card>
      )}

      {/* ===== Step 4: 执行结果 ===== */}
      {currentStep === 4 && execResult && (
        <Card
          title={<Space>{execResult.success ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />} 执行结果</Space>}
          extra={<Button onClick={handleReset}>重新上传</Button>}
        >
          <Descriptions bordered column={2} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="状态">
              <Tag color={execResult.success ? 'green' : 'red'}>{execResult.success ? '成功' : '失败'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="耗时">{execResult.duration}秒</Descriptions.Item>
            <Descriptions.Item label="任务ID">
              {execResult.task_id ? <a href={`/task/${execResult.task_id}`}>#{execResult.task_id}</a> : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="脚本类型">{TYPE_MAP[execResult.script_type]?.label || execResult.script_type}</Descriptions.Item>
          </Descriptions>

          {execResult.output && (
            <>
              <Text strong>输出:</Text>
              <pre style={{ background: '#f6ffed', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto', fontSize: 11, border: '1px solid #b7eb8f' }}>
                {execResult.output}
              </pre>
            </>
          )}

          {execResult.error && (
            <>
              <Text strong style={{ color: 'red' }}>错误:</Text>
              <pre style={{ background: '#fff2f0', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto', fontSize: 11, border: '1px solid #ffccc7' }}>
                {execResult.error}
              </pre>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
