/**
 * 统一需求输入页面
 *
 * 支持多模态输入：文本/图片/PDF/Word/视频/Swagger/数据库Schema
 * 调用 InputRouterAgent 自动路由解析，返回统一的 RequirementContext
 */
import { useState } from 'react';
import {
  Card, Row, Col, Input, Button, Tabs, Upload, message, Spin, Empty, Tag, Space,
  Typography, Collapse, Statistic, Alert, Divider,
} from 'antd';
import {
  FileTextOutlined, PictureOutlined, FilePdfOutlined, VideoCameraOutlined,
  ApiOutlined, DatabaseOutlined, ThunderboltOutlined, InboxOutlined,
  RobotOutlined, CheckCircleOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import {
  parseRequirementInput, uploadRequirementFile,
  type ParseRequest, type ParseResponse, type RequirementContextData,
  SOURCE_TYPE_LABELS, SOURCE_TYPE_COLORS, PRIORITY_COLORS, CATEGORY_LABELS,
} from '../../services/requirementInput';
import AIClassifyCard from '../../components/AIClassifyCard';
import { classifyTestType, type ClassifyResult } from '../../services/testTypeClassifier';

const { TextArea } = Input;
const { Text } = Typography;
const { Dragger } = Upload;

type FileCategory = 'image' | 'pdf' | 'word' | 'video' | 'swagger' | 'schema';

export default function RequirementInputPage() {
  // 文本输入
  const [text, setText] = useState('');

  // 文件列表
  const [imageFiles, setImageFiles] = useState<UploadFile[]>([]);
  const [pdfFiles, setPdfFiles] = useState<UploadFile[]>([]);
  const [wordFiles, setWordFiles] = useState<UploadFile[]>([]);
  const [videoFiles, setVideoFiles] = useState<UploadFile[]>([]);

  // Swagger/Schema 文本输入
  const [swaggerText, setSwaggerText] = useState('');
  const [schemaText, setSchemaText] = useState('');

  // 附加上下文
  const [systemName, setSystemName] = useState('');
  const [businessBg, setBusinessBg] = useState('');
  const [testScope, setTestScope] = useState('');
  const [credentials, setCredentials] = useState('');

  // 已上传文件路径
  const [uploadedPaths, setUploadedPaths] = useState<Record<string, string[]>>({
    image: [], pdf: [], word: [], video: [], swagger: [], schema: [],
  });

  // 解析结果
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ParseResponse | null>(null);

  // AI分类
  const [classifyResult, setClassifyResult] = useState<ClassifyResult | null>(null);
  const [classifyLoading, setClassifyLoading] = useState(false);

  // 文件上传处理
  const handleUpload = async (file: File, category: FileCategory): Promise<string> => {
    try {
      const res = await uploadRequirementFile(file, category);
      if (res.status === 'success') {
        setUploadedPaths(prev => ({
          ...prev,
          [category]: [...prev[category], res.file_path],
        }));
        message.success(`${file.name} 上传成功`);
        return res.file_path;
      } else {
        message.error(`上传失败: ${res.error}`);
        return '';
      }
    } catch (e: any) {
      message.error(`上传失败: ${e?.message}`);
      return '';
    }
  };

  // 文件上传前处理
  const beforeUpload = (category: FileCategory) => async (file: File) => {
    await handleUpload(file, category);
    return false; // 阻止自动上传
  };

  // 执行解析
  const handleParse = async () => {
    if (!text.trim() && !swaggerText.trim() && !schemaText.trim() &&
        uploadedPaths.image.length === 0 && uploadedPaths.pdf.length === 0 &&
        uploadedPaths.word.length === 0 && uploadedPaths.video.length === 0) {
      message.warning('请至少输入一种需求内容');
      return;
    }

    setLoading(true);
    setResult(null);

    const req: ParseRequest = {
      text: text.trim(),
      image_paths: uploadedPaths.image,
      pdf_paths: uploadedPaths.pdf,
      word_paths: uploadedPaths.word,
      video_paths: uploadedPaths.video,
      swagger_content: swaggerText.trim(),
      schema_content: schemaText.trim(),
      context: {
        system_name: systemName,
        business_background: businessBg,
        test_scope: testScope,
        credentials,
      },
    };

    try {
      const res = await parseRequirementInput(req);
      setResult(res);
      if (res.status === 'success') {
        message.success(`解析完成！耗时 ${res.duration}s`);
      } else {
        message.error(`解析失败: ${res.error}`);
      }
    } catch (e: any) {
      message.error(`请求失败: ${e?.message}`);
    } finally {
      setLoading(false);
    }
  };

  // AI分类
  const doClassify = async () => {
    if (!text.trim()) return;
    setClassifyLoading(true);
    try {
      const r = await classifyTestType({ requirement: text.trim(), use_llm: false });
      setClassifyResult(r);
    } catch (e: any) {
      message.error(`AI识别失败: ${e?.message}`);
    } finally {
      setClassifyLoading(false);
    }
  };

  // 重置
  const handleReset = () => {
    setText('');
    setSwaggerText('');
    setSchemaText('');
    setSystemName('');
    setBusinessBg('');
    setTestScope('');
    setCredentials('');
    setImageFiles([]);
    setPdfFiles([]);
    setWordFiles([]);
    setVideoFiles([]);
    setUploadedPaths({ image: [], pdf: [], word: [], video: [], swagger: [], schema: [] });
    setResult(null);
    setClassifyResult(null);
  };

  const ctx: RequirementContextData | null = result?.context as any;

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <RobotOutlined style={{ color: '#1677ff' }} />
            <span>统一需求输入</span>
            <Tag color="blue">企业级</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleParse}
              loading={loading}
              size="large"
            >
              智能解析
            </Button>
            <Button icon={<ReloadOutlined />} onClick={handleReset} disabled={loading}>
              重置
            </Button>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          {/* 左侧：多模态输入 */}
          <Col span={14}>
            <Card title="需求输入" size="small" style={{ marginBottom: 16 }}>
              <Tabs type="card" items={[
                {
                  key: 'text',
                  label: <span><FileTextOutlined /> 文本</span>,
                  children: (
                    <div>
                      <TextArea
                        value={text}
                        onChange={e => setText(e.target.value)}
                        placeholder="请输入测试需求，例如：测试电商系统用户注册登录流程，包括手机号注册、密码登录、第三方登录等场景..."
                        rows={8}
                        onBlur={() => text.trim().length > 5 && doClassify()}
                      />
                      {text.trim().length > 5 && (
                        <div style={{ marginTop: 12 }}>
                          <AIClassifyCard
                            result={classifyResult}
                            loading={classifyLoading}
                            error={null}
                            onChange={(t, f, p) => {
                              // 用户修改AI识别结果
                              void t; void f; void p;
                            }}
                            onReclassify={doClassify}
                          />
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'image',
                  label: <span><PictureOutlined /> 图片</span>,
                  children: (
                    <Dragger
                      listType="picture-card"
                      fileList={imageFiles}
                      beforeUpload={beforeUpload('image')}
                      onRemove={file => {
                        setImageFiles(prev => prev.filter(f => f.uid !== file.uid));
                        setUploadedPaths(prev => ({ ...prev, image: prev.image.slice(0, -1) }));
                      }}
                      accept=".png,.jpg,.jpeg,.webp,.gif,.bmp"
                      multiple
                    >
                      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                      <p className="ant-upload-text">点击或拖拽上传UI截图</p>
                    </Dragger>
                  ),
                },
                {
                  key: 'pdf',
                  label: <span><FilePdfOutlined /> PDF</span>,
                  children: (
                    <Dragger
                      fileList={pdfFiles}
                      beforeUpload={beforeUpload('pdf')}
                      onRemove={file => {
                        setPdfFiles(prev => prev.filter(f => f.uid !== file.uid));
                        setUploadedPaths(prev => ({ ...prev, pdf: prev.pdf.slice(0, -1) }));
                      }}
                      accept=".pdf"
                      multiple
                    >
                      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                      <p className="ant-upload-text">上传PDF需求文档</p>
                    </Dragger>
                  ),
                },
                {
                  key: 'word',
                  label: <span><FileTextOutlined /> Word</span>,
                  children: (
                    <Dragger
                      fileList={wordFiles}
                      beforeUpload={beforeUpload('word')}
                      onRemove={file => {
                        setWordFiles(prev => prev.filter(f => f.uid !== file.uid));
                        setUploadedPaths(prev => ({ ...prev, word: prev.word.slice(0, -1) }));
                      }}
                      accept=".doc,.docx"
                      multiple
                    >
                      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                      <p className="ant-upload-text">上传Word需求文档</p>
                    </Dragger>
                  ),
                },
                {
                  key: 'video',
                  label: <span><VideoCameraOutlined /> 视频</span>,
                  children: (
                    <Dragger
                      fileList={videoFiles}
                      beforeUpload={beforeUpload('video')}
                      onRemove={file => {
                        setVideoFiles(prev => prev.filter(f => f.uid !== file.uid));
                        setUploadedPaths(prev => ({ ...prev, video: prev.video.slice(0, -1) }));
                      }}
                      accept=".mp4,.avi,.mov,.mkv"
                      multiple
                    >
                      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                      <p className="ant-upload-text">上传操作录屏视频</p>
                    </Dragger>
                  ),
                },
                {
                  key: 'swagger',
                  label: <span><ApiOutlined /> Swagger</span>,
                  children: (
                    <TextArea
                      value={swaggerText}
                      onChange={e => setSwaggerText(e.target.value)}
                      placeholder='粘贴 Swagger/OpenAPI JSON 内容，例如：{"openapi":"3.0.0","paths":{"/api/login":{...}}}'
                      rows={8}
                    />
                  ),
                },
                {
                  key: 'schema',
                  label: <span><DatabaseOutlined /> 数据库Schema</span>,
                  children: (
                    <TextArea
                      value={schemaText}
                      onChange={e => setSchemaText(e.target.value)}
                      placeholder="粘贴 DDL SQL，例如：CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100), ...);"
                      rows={8}
                    />
                  ),
                },
              ]} />
            </Card>

            {/* 附加上下文 */}
            <Card title="附加上下文（可选）" size="small">
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                <Input addonBefore="系统名称" value={systemName} onChange={e => setSystemName(e.target.value)} placeholder="如：电商前台系统" />
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>业务背景</Text>
                  <TextArea value={businessBg} onChange={e => setBusinessBg(e.target.value)} placeholder="业务背景描述..." rows={2} />
                </div>
                <Input addonBefore="测试范围" value={testScope} onChange={e => setTestScope(e.target.value)} placeholder="如：前台用户注册登录" />
                <Input addonBefore="测试账号" value={credentials} onChange={e => setCredentials(e.target.value)} placeholder="如：admin/123456" />
              </Space>
            </Card>
          </Col>

          {/* 右侧：解析结果 */}
          <Col span={10}>
            <Card
              title={
                <Space>
                  <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  <span>解析结果</span>
                </Space>
              }
              size="small"
              style={{ maxHeight: 'calc(100vh - 200px)', overflow: 'auto' }}
            >
              {loading && (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <Spin tip="AI正在解析需求..." size="large" />
                </div>
              )}

              {!loading && !result && (
                <Empty description="点击「智能解析」开始分析需求" />
              )}

              {!loading && result && result.status === 'error' && (
                <Alert message="解析失败" description={result.error} type="error" showIcon />
              )}

              {!loading && result && result.status === 'success' && ctx && (
                <div>
                  {/* 统计概览 */}
                  <Row gutter={8} style={{ marginBottom: 16 }}>
                    <Col span={8}>
                      <Statistic title="页面" value={result.pages_count} prefix={<PictureOutlined />} />
                    </Col>
                    <Col span={8}>
                      <Statistic title="元素" value={result.elements_count} prefix={<FileTextOutlined />} />
                    </Col>
                    <Col span={8}>
                      <Statistic title="测试点" value={result.test_points_count} prefix={<ThunderboltOutlined />} />
                    </Col>
                  </Row>

                  <Divider style={{ margin: '8px 0' }} />

                  {/* 来源类型 */}
                  <div style={{ marginBottom: 12 }}>
                    <Text type="secondary">来源类型: </Text>
                    {result.source_types.map(st => (
                      <Tag key={st} color={SOURCE_TYPE_COLORS[st] || 'default'}>
                        {SOURCE_TYPE_LABELS[st] || st}
                      </Tag>
                    ))}
                  </div>

                  {/* 摘要 */}
                  {result.summary && (
                    <Alert
                      message="需求摘要"
                      description={result.summary}
                      type="info"
                      style={{ marginBottom: 12 }}
                    />
                  )}

                  {/* 测试点列表 */}
                  {ctx.test_points && ctx.test_points.length > 0 && (
                    <Collapse
                      size="small"
                      defaultActiveKey={['0']}
                      style={{ marginBottom: 12 }}
                      items={[{
                        key: 'tp',
                        label: <Text strong>测试点 ({ctx.test_points.length})</Text>,
                        children: (
                          <Space direction="vertical" style={{ width: '100%' }} size={8}>
                            {ctx.test_points.map((tp, idx) => (
                              <Card key={idx} size="small" style={{ background: '#fafafa' }}>
                                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                                  <Space>
                                    <Tag color={PRIORITY_COLORS[tp.priority] || 'default'}>
                                      {tp.priority.toUpperCase()}
                                    </Tag>
                                    <Tag>{CATEGORY_LABELS[tp.category] || tp.category}</Tag>
                                    <Text strong>{tp.name}</Text>
                                  </Space>
                                  <Text type="secondary">{tp.description}</Text>
                                </Space>
                              </Card>
                            ))}
                          </Space>
                        ),
                      }]}
                    />
                  )}

                  {/* 业务流程 */}
                  {ctx.business_flow && ctx.business_flow.length > 0 && (
                    <Collapse
                      size="small"
                      style={{ marginBottom: 12 }}
                      items={[{
                        key: 'bf',
                        label: <Text strong>业务流程 ({ctx.business_flow.length})</Text>,
                        children: (
                          <Space direction="vertical" style={{ width: '100%' }} size={8}>
                            {ctx.business_flow.map((flow, idx) => (
                              <Card key={idx} size="small" style={{ background: '#fafafa' }}>
                                <Text strong>{flow.flow_name}</Text>
                                {flow.steps.map((step, sIdx) => (
                                  <div key={sIdx} style={{ marginLeft: 16, marginTop: 4 }}>
                                    <Text type="secondary">{sIdx + 1}. </Text>
                                    <Text>{step.description || step.action || JSON.stringify(step)}</Text>
                                  </div>
                                ))}
                              </Card>
                            ))}
                          </Space>
                        ),
                      }]}
                    />
                  )}

                  {/* 约束条件 */}
                  {ctx.constraints && ctx.constraints.length > 0 && (
                    <Collapse
                      size="small"
                      style={{ marginBottom: 12 }}
                      items={[{
                        key: 'cs',
                        label: <Text strong>约束条件 ({ctx.constraints.length})</Text>,
                        children: (
                          <Space direction="vertical" style={{ width: '100%' }} size={4}>
                            {ctx.constraints.map((c, idx) => (
                              <div key={idx}>
                                <Tag>{c.type}</Tag>
                                <Text>{c.description}</Text>
                                {c.source && <Text type="secondary"> ({c.source})</Text>}
                              </div>
                            ))}
                          </Space>
                        ),
                      }]}
                    />
                  )}

                  {/* 耗时 */}
                  <Divider style={{ margin: '8px 0' }} />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    解析耗时: {result.duration}s
                  </Text>
                </div>
              )}
            </Card>
          </Col>
        </Row>
      </Card>
    </div>
  );
}
