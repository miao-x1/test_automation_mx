/**
 * API 接口管理 - 编辑/新建页
 *
 * 路由:
 *   /asset/endpoints/new        - 新建
 *   /asset/endpoints/:id/edit   - 编辑
 *
 * 功能:
 *   1. 基本信息表单(名称 / 方法 / 路径 / 摘要 / 描述 / 模块 / 标签)
 *   2. 请求头 (动态增删)
 *   3. 参数列表 (动态增删, 包含位置 / 类型 / 必填 / 默认 / 示例 / 说明)
 *   4. 请求体 (Content-Type 选择 + Raw / JSON Schema / 示例)
 *   5. 响应 (状态码 + 响应头 + 响应体 Schema + 示例)
 *   6. 认证 (类型 + 详情 JSON)
 *   7. 保存 (新建 = POST, 编辑 = PUT)
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Input,
  Select,
  Form,
  Space,
  message,
  Typography,
  Tabs,
  Table,
  Switch,
  InputNumber,
  Spin,
  Row,
  Col,
} from 'antd';
import {
  ArrowLeftOutlined,
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getEndpoint,
  createEndpoint,
  updateEndpoint,
  type ApiEndpoint,
  type EndpointCreateInput,
  type HeaderItem,
  type ParamItem,
  type BodySpec,
  type ResponseSpec,
  type AuthSpec,
  type AuthType,
  type HTTPMethod,
  type EndpointSource,
} from '@/services/apiEndpoint';

const { Title } = Typography;
const { TextArea } = Input;

// HTTP 方法列表
const HTTP_METHODS: HTTPMethod[] = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];

// 认证类型
const AUTH_TYPES: AuthType[] = ['none', 'basic', 'bearer', 'api_key', 'oauth2', 'custom'];

// 接口来源
const SOURCES: EndpointSource[] = ['manual', 'swagger', 'postman', 'har', 'import', 'ai'];

// 参数位置
const PARAM_LOCATIONS = ['query', 'path', 'header', 'cookie'];
// 参数类型
const PARAM_TYPES = ['string', 'integer', 'boolean', 'number', 'array', 'object'];

// 默认空表单
const EMPTY_FORM: EndpointCreateInput = {
  name: '',
  method: 'GET',
  path: '/',
  summary: '',
  description: '',
  tags: [],
  module: '',
  status: 'draft',
  source: 'manual',
  headers: [],
  params: [],
  body: { content_type: 'application/json', raw: '', example: null },
  response: { status_code: 200, desc: '' },
  auth: { type: 'none' },
};

export default function EndpointEditPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  // id === 'new' 表示新建,否则为编辑现有接口
  const isEdit = !!id && id !== 'new';
  const endpointId = isEdit ? Number(id) : null;

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<EndpointCreateInput>(EMPTY_FORM);

  // 拉取现有接口
  const fetchEndpoint = useCallback(async () => {
    if (!endpointId) return;
    setLoading(true);
    try {
      const res: ApiEndpoint = await getEndpoint(endpointId);
      // 拍平为表单格式
      setForm({
        name: res.name || '',
        method: res.method,
        path: res.path || '/',
        summary: res.summary || '',
        description: res.description || '',
        tags: res.tags || [],
        module: res.module || '',
        status: res.status,
        source: res.source,
        headers: res.headers || [],
        params: res.params || [],
        body: res.body || { content_type: 'application/json', raw: '' },
        response: res.response || { status_code: 200, desc: '' },
        auth: res.auth || { type: 'none' },
      });
    } catch (e: any) {
      message.error(e?.message || '加载接口失败');
      navigate('/asset/endpoints');
    } finally {
      setLoading(false);
    }
  }, [endpointId, navigate]);

  useEffect(() => {
    if (isEdit) fetchEndpoint();
  }, [isEdit, fetchEndpoint]);

  // 表单字段更新辅助
  const updateField = <K extends keyof EndpointCreateInput>(
    key: K,
    value: EndpointCreateInput[K],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  // ===== Headers 操作 =====
  const addHeader = () => {
    const newHeader: HeaderItem = { key: '', value: '', desc: '' };
    updateField('headers', [...(form.headers || []), newHeader]);
  };
  const updateHeader = (index: number, field: keyof HeaderItem, value: string) => {
    const list = [...(form.headers || [])];
    list[index] = { ...list[index], [field]: value };
    updateField('headers', list);
  };
  const removeHeader = (index: number) => {
    const list = [...(form.headers || [])];
    list.splice(index, 1);
    updateField('headers', list);
  };

  // ===== Params 操作 =====
  const addParam = () => {
    const newParam: ParamItem = {
      name: '',
      location: 'query',
      type: 'string',
      required: false,
      desc: '',
    };
    updateField('params', [...(form.params || []), newParam]);
  };
  const updateParam = (index: number, field: keyof ParamItem, value: unknown) => {
    const list = [...(form.params || [])];
    list[index] = { ...list[index], [field]: value } as ParamItem;
    updateField('params', list);
  };
  const removeParam = (index: number) => {
    const list = [...(form.params || [])];
    list.splice(index, 1);
    updateField('params', list);
  };

  // ===== Body 操作 =====
  const updateBody = (field: keyof BodySpec, value: unknown) => {
    updateField('body', { ...form.body, [field]: value } as BodySpec);
  };

  // ===== Response 操作 =====
  const updateResponse = (field: keyof ResponseSpec, value: unknown) => {
    updateField('response', { ...form.response, [field]: value } as ResponseSpec);
  };

  // ===== Auth 操作 =====
  const updateAuth = (field: keyof AuthSpec, value: unknown) => {
    updateField('auth', { ...form.auth, [field]: value } as AuthSpec);
  };

  // 表单校验
  const validate = (): string | null => {
    if (!form.name?.trim()) return '接口名称不能为空';
    if (!form.method) return '请选择 HTTP 方法';
    if (!form.path?.trim()) return '接口路径不能为空';
    if (!form.path.startsWith('/')) return '路径必须以 / 开头';
    return null;
  };

  // 保存
  const handleSave = async () => {
    const error = validate();
    if (error) {
      message.warning(error);
      return;
    }

    setSaving(true);
    try {
      // 清理空值
      const payload: EndpointCreateInput = {
        ...form,
        name: form.name.trim(),
        path: form.path.trim(),
        summary: form.summary?.trim() || undefined,
        description: form.description?.trim() || undefined,
        module: form.module?.trim() || undefined,
        tags: form.tags?.length ? form.tags : undefined,
        headers: form.headers?.filter((h) => h.key) || undefined,
        params: form.params?.filter((p) => p.name) || undefined,
      };

      if (isEdit && endpointId) {
        const updated = await updateEndpoint(endpointId, payload);
        message.success('更新成功');
        navigate(`/asset/endpoints/${updated.id}`);
      } else {
        const created = await createEndpoint(payload);
        message.success('创建成功');
        navigate(`/asset/endpoints/${created.id}`);
      }
    } catch (e: any) {
      message.error(e?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  // Tab 项配置
  const tabItems = [
    {
      key: 'basic',
      label: '基本信息',
      children: (
        <Form layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="接口名称" required>
                <Input
                  placeholder="如: 创建用户"
                  value={form.name}
                  onChange={(e) => updateField('name', e.target.value)}
                  maxLength={200}
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="HTTP 方法" required>
                <Select
                  value={form.method}
                  onChange={(v) => updateField('method', v)}
                  options={HTTP_METHODS.map((m) => ({ value: m, label: m }))}
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="状态">
                <Select
                  value={form.status}
                  onChange={(v) => updateField('status', v)}
                  options={[
                    { value: 'draft', label: '草稿' },
                    { value: 'active', label: '已发布' },
                    { value: 'deprecated', label: '已弃用' },
                    { value: 'archived', label: '已归档' },
                  ]}
                  disabled={isEdit}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="路径" required>
            <Input
              placeholder="如: /api/v1/users"
              value={form.path}
              onChange={(e) => updateField('path', e.target.value)}
              maxLength={500}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="所属模块">
                <Input
                  placeholder="如: 用户管理"
                  value={form.module}
                  onChange={(e) => updateField('module', e.target.value)}
                  maxLength={100}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="来源">
                <Select
                  value={form.source}
                  onChange={(v) => updateField('source', v)}
                  options={SOURCES.map((s) => ({ value: s, label: s }))}
                  disabled={isEdit}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="标签">
            <Select
              mode="tags"
              placeholder="输入后按回车添加标签"
              value={form.tags}
              onChange={(v) => updateField('tags', v)}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item label="摘要">
            <Input
              placeholder="一句话描述"
              value={form.summary}
              onChange={(e) => updateField('summary', e.target.value)}
              maxLength={500}
            />
          </Form.Item>

          <Form.Item label="详细说明">
            <TextArea
              rows={4}
              placeholder="支持多行"
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
            />
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'headers',
      label: `请求头 (${form.headers?.length || 0})`,
      children: (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={addHeader}>
              添加请求头
            </Button>
          </Space>
          <Table
            dataSource={form.headers || []}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            columns={[
              {
                title: 'Key',
                dataIndex: 'key',
                width: 220,
                render: (_: unknown, _r: HeaderItem, i: number) => (
                  <Input value={form.headers?.[i]?.key} onChange={(e) => updateHeader(i, 'key', e.target.value)} />
                ),
              },
              {
                title: 'Value',
                dataIndex: 'value',
                render: (_: unknown, _r: HeaderItem, i: number) => (
                  <Input value={form.headers?.[i]?.value} onChange={(e) => updateHeader(i, 'value', e.target.value)} />
                ),
              },
              {
                title: '说明',
                dataIndex: 'desc',
                width: 200,
                render: (_: unknown, _r: HeaderItem, i: number) => (
                  <Input value={form.headers?.[i]?.desc} onChange={(e) => updateHeader(i, 'desc', e.target.value)} />
                ),
              },
              {
                title: '操作',
                key: 'action',
                width: 70,
                render: (_: unknown, _r: HeaderItem, i: number) => (
                  <Button type="link" danger icon={<DeleteOutlined />} onClick={() => removeHeader(i)} />
                ),
              },
            ]}
          />
        </div>
      ),
    },
    {
      key: 'params',
      label: `参数 (${form.params?.length || 0})`,
      children: (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={addParam}>
              添加参数
            </Button>
          </Space>
          <Table
            dataSource={form.params || []}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            scroll={{ x: 1000 }}
            columns={[
              {
                title: '参数名',
                dataIndex: 'name',
                width: 150,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Input
                    value={form.params?.[i]?.name}
                    onChange={(e) => updateParam(i, 'name', e.target.value)}
                    placeholder="如: user_id"
                  />
                ),
              },
              {
                title: '位置',
                dataIndex: 'location',
                width: 100,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Select
                    value={form.params?.[i]?.location || 'query'}
                    onChange={(v) => updateParam(i, 'location', v)}
                    style={{ width: '100%' }}
                    options={PARAM_LOCATIONS.map((l) => ({ value: l, label: l }))}
                  />
                ),
              },
              {
                title: '类型',
                dataIndex: 'type',
                width: 100,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Select
                    value={form.params?.[i]?.type || 'string'}
                    onChange={(v) => updateParam(i, 'type', v)}
                    style={{ width: '100%' }}
                    options={PARAM_TYPES.map((t) => ({ value: t, label: t }))}
                  />
                ),
              },
              {
                title: '必填',
                dataIndex: 'required',
                width: 70,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Switch
                    checked={!!form.params?.[i]?.required}
                    onChange={(v) => updateParam(i, 'required', v)}
                  />
                ),
              },
              {
                title: '默认值',
                dataIndex: 'default',
                width: 130,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Input
                    value={form.params?.[i]?.default || ''}
                    onChange={(e) => updateParam(i, 'default', e.target.value)}
                  />
                ),
              },
              {
                title: '示例',
                dataIndex: 'example',
                width: 130,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Input
                    value={form.params?.[i]?.example || ''}
                    onChange={(e) => updateParam(i, 'example', e.target.value)}
                  />
                ),
              },
              {
                title: '说明',
                dataIndex: 'desc',
                width: 180,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Input
                    value={form.params?.[i]?.desc || ''}
                    onChange={(e) => updateParam(i, 'desc', e.target.value)}
                  />
                ),
              },
              {
                title: '操作',
                key: 'action',
                width: 70,
                render: (_: unknown, _r: ParamItem, i: number) => (
                  <Button type="link" danger icon={<DeleteOutlined />} onClick={() => removeParam(i)} />
                ),
              },
            ]}
          />
        </div>
      ),
    },
    {
      key: 'body',
      label: '请求体',
      children: (
        <Form layout="vertical">
          <Form.Item label="Content-Type">
            <Select
              value={form.body?.content_type || 'application/json'}
              onChange={(v) => updateBody('content_type', v)}
              options={[
                { value: 'application/json', label: 'application/json' },
                { value: 'form-data', label: 'multipart/form-data' },
                { value: 'x-www-form-urlencoded', label: 'application/x-www-form-urlencoded' },
                { value: 'raw', label: 'raw' },
              ]}
              style={{ width: 300 }}
            />
          </Form.Item>
          <Form.Item label="原始文本 (Raw)">
            <TextArea
              rows={6}
              placeholder="支持任意文本,如 JSON / XML"
              value={form.body?.raw || ''}
              onChange={(e) => updateBody('raw', e.target.value)}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
          <Form.Item label="示例 (JSON 字符串)">
            <TextArea
              rows={6}
              placeholder='如: {"name": "alice", "age": 18}'
              value={typeof form.body?.example === 'string' ? form.body.example : (form.body?.example ? JSON.stringify(form.body.example, null, 2) : '')}
              onChange={(e) => updateBody('example', e.target.value)}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
          <Form.Item label="JSON Schema (JSON 字符串)">
            <TextArea
              rows={6}
              placeholder='如: {"type": "object", "properties": {...}}'
              value={form.body?.json_schema ? (typeof form.body.json_schema === 'string' ? form.body.json_schema : JSON.stringify(form.body.json_schema, null, 2)) : ''}
              onChange={(e) => {
                // 尝试解析为对象,失败则保留为字符串
                try {
                  const parsed = e.target.value ? JSON.parse(e.target.value) : null;
                  updateBody('json_schema', parsed);
                } catch {
                  // 解析失败时,不更新(避免输入中途报错)
                }
              }}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'response',
      label: '响应',
      children: (
        <Form layout="vertical">
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item label="状态码">
                <InputNumber
                  value={form.response?.status_code || 200}
                  onChange={(v) => updateResponse('status_code', v || 200)}
                  min={100}
                  max={599}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
            <Col span={18}>
              <Form.Item label="说明">
                <Input
                  value={form.response?.desc || ''}
                  onChange={(e) => updateResponse('desc', e.target.value)}
                  placeholder="响应说明"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="响应体 Schema (JSON 字符串)">
            <TextArea
              rows={6}
              placeholder='如: {"type": "object", "properties": {"id": {"type": "integer"}}}'
              value={form.response?.body_schema ? (typeof form.response.body_schema === 'string' ? form.response.body_schema : JSON.stringify(form.response.body_schema, null, 2)) : ''}
              onChange={(e) => {
                try {
                  const parsed = e.target.value ? JSON.parse(e.target.value) : null;
                  updateResponse('body_schema', parsed);
                } catch {
                  // 解析失败时,不更新
                }
              }}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
          <Form.Item label="响应示例 (JSON 字符串)">
            <TextArea
              rows={6}
              placeholder='如: {"id": 1, "name": "alice"}'
              value={form.response?.example != null ? (typeof form.response.example === 'string' ? form.response.example : JSON.stringify(form.response.example, null, 2)) : ''}
              onChange={(e) => updateResponse('example', e.target.value)}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'auth',
      label: '认证',
      children: (
        <Form layout="vertical">
          <Form.Item label="认证类型">
            <Select
              value={form.auth?.type || 'none'}
              onChange={(v) => updateAuth('type', v)}
              style={{ width: 300 }}
              options={AUTH_TYPES.map((t) => ({ value: t, label: t }))}
            />
          </Form.Item>
          <Form.Item label="认证详情 (JSON 字符串)">
            <TextArea
              rows={6}
              placeholder='如: {"token": "Bearer xxx", "header_name": "Authorization"}'
              value={form.auth?.details ? (typeof form.auth.details === 'string' ? form.auth.details : JSON.stringify(form.auth.details, null, 2)) : ''}
              onChange={(e) => {
                try {
                  const parsed = e.target.value ? JSON.parse(e.target.value) : null;
                  updateAuth('details', parsed);
                } catch {
                  // 解析失败时,不更新
                }
              }}
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>
        </Form>
      ),
    },
  ];

  return (
    <div>
      {/* 顶部操作条 */}
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <Title level={4} style={{ margin: 0 }}>
            {isEdit ? '编辑接口' : '新建接口'}
          </Title>
        </Space>
      </Card>

      {/* 表单 */}
      <Card>
        <Tabs defaultActiveKey="basic" items={tabItems} />

        {/* 底部操作 */}
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid #f0f0f0', textAlign: 'right' }}>
          <Space>
            <Button onClick={() => navigate(-1)}>取消</Button>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
              {isEdit ? '保存修改' : '创建接口'}
            </Button>
          </Space>
        </div>
      </Card>
    </div>
  );
}
