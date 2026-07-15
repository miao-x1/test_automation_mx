/**
 * RequirementInput — 统一多模态需求输入组件
 *
 * 所有输入类型在同一面板，支持混合输入
 * 智能推荐：检测到图片→Vision模式，URL→DOM模式，脚本→复用模式
 */
import { useState, useCallback, useEffect } from 'react';
import {
  Card, Input, Button, Space, Typography, Tag, Upload, message, Alert,
  Tooltip, Divider,
} from 'antd';
import {
  FileTextOutlined, PictureOutlined, LinkOutlined, CodeOutlined,
  CloudUploadOutlined, DeleteOutlined, EyeOutlined, BulbOutlined,
  RobotOutlined, PlusOutlined,
} from '@ant-design/icons';
import { uploadImages, uploadScript } from '../services/multimodalInput';
import type { RecommendedMode } from '../services/multimodalInput';

const { Text } = Typography;
const { TextArea } = Input;

const MODE_CONFIG: Record<RecommendedMode, { label: string; color: string; icon: React.ReactNode; desc: string }> = {
  vision: { label: 'Vision模式', color: 'purple', icon: <EyeOutlined />, desc: '图片UI元素识别+需求提取' },
  dom: { label: 'DOM模式', color: 'blue', icon: <LinkOutlined />, desc: '自动抓取页面结构和元素' },
  reuse: { label: '复用模式', color: 'green', icon: <CodeOutlined />, desc: '基于已有脚本逻辑生成测试' },
  text: { label: '文本模式', color: 'default', icon: <FileTextOutlined />, desc: '标准文本解析模式' },
};

interface RequirementInputProps {
  onSubmit: (data: {
    text?: string;
    images?: string[];
    urls?: string[];
    script_content?: string;
    script_language?: string;
  }) => void;
  loading?: boolean;
}

export function RequirementInput({ onSubmit, loading = false }: RequirementInputProps) {
  const [text, setText] = useState('');
  const [imagePaths, setImagePaths] = useState<string[]>([]);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [urls, setUrls] = useState<string[]>([]);
  const [urlInput, setUrlInput] = useState('');
  const [scriptContent, setScriptContent] = useState('');
  const [scriptLanguage, setScriptLanguage] = useState('python');
  const [scriptFileName, setScriptFileName] = useState('');

  // 推荐状态
  const [recommendedMode, setRecommendedMode] = useState<RecommendedMode>('text');
  const [recommendedReason, setRecommendedReason] = useState('');

  // 智能推荐检测
  useEffect(() => {
    const hasImages = imagePaths.length > 0;
    const hasUrls = urls.length > 0;
    const hasScript = !!scriptContent.trim();
    const hasText = !!text.trim();

    if (hasImages && !hasText) {
      setRecommendedMode('vision');
      setRecommendedReason('检测到图片输入，推荐Vision模式');
    } else if (hasImages && hasText) {
      setRecommendedMode('vision');
      setRecommendedReason('图片+文本混合，Vision模式增强UI理解');
    } else if (hasUrls && !hasText) {
      setRecommendedMode('dom');
      setRecommendedReason('检测到URL输入，推荐DOM模式');
    } else if (hasUrls && hasText) {
      setRecommendedMode('dom');
      setRecommendedReason('URL+文本输入，DOM模式提取页面元素');
    } else if (hasScript) {
      setRecommendedMode('reuse');
      setRecommendedReason('检测到脚本输入，推荐复用模式');
    } else {
      setRecommendedMode('text');
      setRecommendedReason('纯文本输入，标准解析模式');
    }
  }, [imagePaths.length, urls.length, scriptContent, text]);

  // 图片上传
  const handleImageUpload = useCallback(async (file: File) => {
    try {
      const result = await uploadImages([file]);
      if (result.image_paths) {
        setImagePaths(prev => [...prev, ...result.image_paths]);
        setImageUrls(prev => [...prev, ...result.image_paths.map((p: string) => `/api/requirement/images/${p}`)]);
        message.success('图片上传成功');
      }
    } catch {
      message.error('图片上传失败');
    }
  }, []);

  // 脚本上传
  const handleScriptUpload = useCallback(async (file: File) => {
    try {
      const result = await uploadScript(file);
      setScriptContent(result.script_content);
      setScriptLanguage(result.script_language);
      setScriptFileName(result.filename);
      message.success('脚本上传成功');
    } catch {
      message.error('脚本上传失败');
    }
  }, []);

  // 添加URL
  const handleAddUrl = useCallback(() => {
    const url = urlInput.trim();
    if (!url) return;
    if (!url.match(/^https?:\/\/.+/)) {
      message.warning('请输入有效的URL');
      return;
    }
    if (urls.includes(url)) {
      message.warning('URL已存在');
      return;
    }
    setUrls(prev => [...prev, url]);
    setUrlInput('');
  }, [urlInput, urls]);

  const handleRemoveUrl = useCallback((index: number) => {
    setUrls(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleRemoveImage = useCallback((index: number) => {
    setImagePaths(prev => prev.filter((_, i) => i !== index));
    setImageUrls(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleClearScript = useCallback(() => {
    setScriptContent('');
    setScriptFileName('');
  }, []);

  // 提交
  const handleSubmit = useCallback(() => {
    const hasInput = text.trim() || imagePaths.length > 0 || urls.length > 0 || scriptContent.trim();
    if (!hasInput) {
      message.warning('请至少输入一种需求');
      return;
    }
    onSubmit({
      text: text.trim() || undefined,
      images: imagePaths.length > 0 ? imagePaths : undefined,
      urls: urls.length > 0 ? urls : undefined,
      script_content: scriptContent.trim() || undefined,
      script_language: scriptLanguage || undefined,
    });
  }, [text, imagePaths, urls, scriptContent, scriptLanguage, onSubmit]);

  const activeInputCount = [
    text.trim() ? 1 : 0,
    imagePaths.length > 0 ? 1 : 0,
    urls.length > 0 ? 1 : 0,
    scriptContent.trim() ? 1 : 0,
  ].reduce((a, b) => a + b, 0);

  const isMixed = activeInputCount > 1;
  const modeConfig = MODE_CONFIG[recommendedMode];

  return (
    <Card
      size="small"
      title={
        <Space>
          <FileTextOutlined />
          <span>需求输入</span>
          {isMixed && <Tag color="orange">混合输入</Tag>}
        </Space>
      }
      extra={
        recommendedMode !== 'text' ? (
          <Tooltip title={recommendedReason}>
            <Tag color={modeConfig.color} style={{ cursor: 'pointer' }}>
              {modeConfig.icon} {modeConfig.label}
            </Tag>
          </Tooltip>
        ) : null
      }
    >
      {/* 智能推荐提示 */}
      {recommendedMode !== 'text' && (
        <Alert
          type="info"
          showIcon
          icon={<BulbOutlined />}
          message={
            <Space>
              <Text strong>智能推荐: {modeConfig.label}</Text>
              <Text type="secondary">{recommendedReason}</Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
          closable
        />
      )}

      {/* ===== 文本输入 ===== */}
      <TextArea
        placeholder="输入测试需求，如：测试登录功能..."
        value={text}
        onChange={e => setText(e.target.value)}
        autoSize={{ minRows: 2, maxRows: 6 }}
        disabled={loading}
        style={{ marginBottom: 8 }}
      />
      <Space wrap style={{ marginBottom: 8 }}>
        {['测试登录功能', '测试商品搜索', '测试购物车功能', '测试注册流程'].map(ex => (
          <Tag key={ex} color="blue" style={{ cursor: 'pointer', fontSize: 11 }} onClick={() => setText(ex)}>
            {ex}
          </Tag>
        ))}
      </Space>

      <Divider style={{ margin: '8px 0' }} />

      {/* ===== 图片 + URL + 脚本 — 并排一行 ===== */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {/* 图片上传 */}
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>
            <PictureOutlined /> 截图
          </Text>
          <Upload
            listType="picture-card"
            accept="image/*"
            multiple
            fileList={imageUrls.map((url, i) => ({
              uid: `-${i}`, name: `screenshot-${i}`, status: 'done' as const, url,
            }))}
            customRequest={({ file, onSuccess }) => {
              handleImageUpload(file as File);
              onSuccess?.(null);
            }}
            onRemove={file => {
              const idx = imageUrls.indexOf(file.url || '');
              if (idx >= 0) handleRemoveImage(idx);
            }}
          >
            {imageUrls.length < 5 && (
              <div><PlusOutlined /><div style={{ fontSize: 11 }}>上传</div></div>
            )}
          </Upload>
        </div>

        {/* URL + 脚本 */}
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          {/* URL输入 */}
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>
            <LinkOutlined /> 页面URL
          </Text>
          <Space.Compact style={{ width: '100%', marginBottom: 4 }}>
            <Input
              placeholder="https://..."
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              onPressEnter={handleAddUrl}
              disabled={loading}
              size="small"
            />
            <Button size="small" onClick={handleAddUrl} disabled={!urlInput.trim()}>
              添加
            </Button>
          </Space.Compact>
          {urls.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
              {urls.map((url, i) => (
                <Tag key={url} closable onClose={() => handleRemoveUrl(i)} color="blue" icon={<LinkOutlined />}
                  style={{ fontSize: 11 }}>
                  {url.length > 25 ? url.substring(0, 25) + '...' : url}
                </Tag>
              ))}
            </div>
          )}

          {/* 脚本上传 */}
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block', marginTop: 4 }}>
            <CodeOutlined /> 脚本
          </Text>
          {!scriptContent.trim() ? (
            <Upload
              accept=".py,.js,.ts,.yaml,.yml"
              maxCount={1}
              showUploadList={false}
              customRequest={({ file, onSuccess, onError }) => {
                handleScriptUpload(file as File)
                  .then(() => onSuccess?.(null))
                  .catch((err) => onError?.(err));
              }}
            >
              <Button size="small" icon={<CloudUploadOutlined />} block>
                上传脚本
              </Button>
            </Upload>
          ) : (
            <div>
              <Space size="small">
                <Tag color="green" icon={<CodeOutlined />} style={{ fontSize: 11 }}>
                  {scriptFileName || scriptLanguage}
                </Tag>
                <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={handleClearScript} />
              </Space>
            </div>
          )}
        </div>
      </div>

      {/* 提交按钮 */}
      <Button
        type="primary"
        block
        icon={<RobotOutlined />}
        onClick={handleSubmit}
        loading={loading}
        disabled={activeInputCount === 0}
        size="large"
        style={{ marginTop: 12 }}
      >
        {loading ? '分析中...' : isMixed ? '多模态分析' : '创建需求 & 开始分析'}
      </Button>
    </Card>
  );
}
