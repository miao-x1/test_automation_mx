/**
 * 测试资产中心 - 资产编辑页
 *
 * 路由:
 *   /asset/center/new        - 新建资产
 *   /asset/center/:id/edit   - 编辑资产
 *
 * 字段:
 *   - asset_code (可选, 不填自动生成; 仅新建时可填)
 *   - name / asset_type / ref_type / ref_id (仅新建时可改)
 *   - summary / description / module / tags / source
 *   - extra_metadata (JSON 编辑器)
 *   - quality_score (仅编辑模式)
 *
 * 约束:
 *   - archived 状态不允许编辑 (提示需先恢复为 draft)
 *   - ref_id 允许 0 (纯索引资产)
 *   - ref_type 必须与 asset_type 一致 (test_data 除外)
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Space,
  message,
  Typography,
  InputNumber,
  Alert,
  Divider,
  Tag,
} from 'antd';
import {
  ArrowLeftOutlined,
  SaveOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getAsset,
  createAsset,
  updateAsset,
  type Asset,
  type AssetCreateInput,
  type AssetType,
  type AssetSource,
  type AssetUpdateInput,
} from '@/services/assetCenter';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// 资产类型选项
const ASSET_TYPE_OPTIONS: Array<{ value: AssetType | string; label: string; refType: string }> = [
  { value: 'api_endpoint', label: 'API 接口', refType: 'api_endpoint' },
  { value: 'ui_element', label: 'UI 元素', refType: 'ui_element' },
  { value: 'test_case', label: '测试用例', refType: 'test_case' },
  { value: 'test_asset', label: '测试资产', refType: 'test_asset' },
  { value: 'script', label: '测试脚本', refType: 'script' },
  { value: 'test_data', label: '测试数据 (纯索引)', refType: 'test_data' },
  { value: 'test_report', label: '测试报告', refType: 'test_report' },
  { value: 'requirement', label: '需求', refType: 'requirement' },
];

// 来源选项
const SOURCE_OPTIONS: Array<{ value: AssetSource | string; label: string }> = [
  { value: 'manual', label: '手工录入' },
  { value: 'swagger', label: 'Swagger 导入' },
  { value: 'postman', label: 'Postman 导入' },
  { value: 'har', label: 'HAR 抓包' },
  { value: 'import', label: '批量导入' },
  { value: 'ai', label: 'AI 生成' },
];

// ref_type 选项
const REF_TYPE_OPTIONS = [
  { value: 'api_endpoint', label: 'api_endpoint' },
  { value: 'ui_element', label: 'ui_element' },
  { value: 'test_case', label: 'test_case' },
  { value: 'test_asset', label: 'test_asset' },
  { value: 'script', label: 'script' },
  { value: 'test_data', label: 'test_data' },
  { value: 'test_report', label: 'test_report' },
  { value: 'requirement', label: 'requirement' },
];

export default function AssetCenterEditPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const assetId = id ? Number(id) : null;
  const isEdit = assetId !== null;

  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [asset, setAsset] = useState<Asset | null>(null);
  const [assetType, setAssetType] = useState<string>('api_endpoint');
  const [extraMetadataStr, setExtraMetadataStr] = useState<string>('{}');

  // 加载资产
  const fetchAsset = useCallback(async () => {
    if (!assetId) return;
    setLoading(true);
    try {
      const res = await getAsset(assetId);
      setAsset(res);
      setAssetType(res.asset_type);
      form.setFieldsValue({
        asset_code: res.asset_code,
        name: res.name,
        asset_type: res.asset_type,
        ref_type: res.ref_type,
        ref_id: res.ref_id,
        summary: res.summary,
        description: res.description,
        module: res.module,
        tags: res.tags,
        source: res.source,
        quality_score: res.quality_score,
      });
      setExtraMetadataStr(JSON.stringify(res.extra_metadata ?? {}, null, 2));
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载资产详情失败');
    } finally {
      setLoading(false);
    }
  }, [assetId, form]);

  useEffect(() => {
    if (isEdit) {
      fetchAsset();
    } else {
      // 新建默认值
      form.setFieldsValue({
        ref_id: 0,
        source: 'manual',
        quality_score: 0,
        asset_type: 'api_endpoint',
        ref_type: 'api_endpoint',
      });
      setAssetType('api_endpoint');
      setExtraMetadataStr('{}');
    }
  }, [isEdit, fetchAsset, form]);

  // 资产类型变化时自动同步 ref_type (test_data 独立)
  const handleAssetTypeChange = (value: string) => {
    setAssetType(value);
    const currentRefType = form.getFieldValue('ref_type');
    // 仅当 ref_type 未被用户特殊配置时自动同步
    const matchingOption = ASSET_TYPE_OPTIONS.find(o => o.value === value);
    if (matchingOption && (currentRefType === '' || currentRefType === undefined || ASSET_TYPE_OPTIONS.some(o => o.refType === currentRefType))) {
      form.setFieldValue('ref_type', matchingOption.refType);
    }
  };

  // 保存
  const handleSave = async () => {
    try {
      const values = await form.validateFields();

      // 校验 extra_metadata 是否合法 JSON
      let extraMetadata: Record<string, unknown> | undefined = undefined;
      if (extraMetadataStr && extraMetadataStr.trim() !== '{}') {
        try {
          extraMetadata = JSON.parse(extraMetadataStr);
        } catch {
          message.error('扩展元数据不是合法的 JSON');
          return;
        }
      }

      setSaving(true);
      if (isEdit && assetId) {
        // 编辑模式
        const updateData: AssetUpdateInput = {
          name: values.name,
          summary: values.summary,
          description: values.description,
          module: values.module,
          tags: values.tags,
          quality_score: values.quality_score,
        };
        if (extraMetadata) updateData.extra_metadata = extraMetadata;

        await updateAsset(assetId, updateData);
        message.success('保存成功');
        navigate(`/asset/center/${assetId}`);
      } else {
        // 新建模式
        const createData: AssetCreateInput = {
          asset_code: values.asset_code || undefined,
          name: values.name,
          asset_type: values.asset_type,
          ref_type: values.ref_type,
          ref_id: values.ref_id ?? 0,
          summary: values.summary,
          description: values.description,
          module: values.module,
          tags: values.tags,
          source: values.source || 'manual',
        };
        if (extraMetadata) createData.extra_metadata = extraMetadata;

        const newAsset = await createAsset(createData);
        message.success(`资产已创建: ${newAsset.asset_code}`);
        navigate(`/asset/center/${newAsset.id}`);
      }
    } catch (e: unknown) {
      if ((e as { errorFields?: unknown })?.errorFields) return;
      const err = e as { message?: string };
      message.error(err?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // archived 状态不允许编辑
  const isArchived = asset?.status === 'archived';

  return (
    <div>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: '12px 24px' } }}
      >
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space>
            <Button onClick={() => navigate(-1)} icon={<ArrowLeftOutlined />}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              {isEdit ? '编辑资产' : '新建资产'}
            </Title>
            {asset && (
              <>
                <Tag style={{ fontFamily: 'monospace', fontSize: 11, color: '#8c8c8c' }}>{asset.asset_code}</Tag>
                <Tag color="blue">v{asset.version}</Tag>
                <Tag color={asset.status === 'active' ? 'green' : 'orange'}>{asset.status}</Tag>
              </>
            )}
          </Space>
          <Space>
            {isEdit && assetId && (
              <Button onClick={() => navigate(`/asset/center/${assetId}`)} icon={<EyeOutlined />}>
                查看详情
              </Button>
            )}
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
              disabled={isArchived}
            >
              保存
            </Button>
          </Space>
        </Space>
      </Card>

      {isArchived && (
        <Alert
          message="归档状态资产不允许编辑"
          description="请先在详情页将状态变更为 draft (恢复) 后再编辑"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Card loading={loading}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            ref_id: 0,
            source: 'manual',
            quality_score: 0,
          }}
        >
          {/* 基本信息 */}
          <Divider orientation="left">基本信息</Divider>
          <Form.Item
            name="asset_code"
            label="资产编码"
            tooltip="留空系统自动生成 (ASSET-YYYY-NNNN); 编辑模式下不可修改"
          >
            <Input
              placeholder="留空自动生成, 例: ASSET-2026-0001"
              disabled={isEdit}
              maxLength={64}
            />
          </Form.Item>

          <Form.Item
            name="name"
            label="资产名称"
            rules={[{ required: true, message: '请输入资产名称' }, { max: 200 }]}
          >
            <Input placeholder="例: 用户登录接口" maxLength={200} />
          </Form.Item>

          <Form.Item
            name="asset_type"
            label="资产类型"
            rules={[{ required: true, message: '请选择资产类型' }]}
            tooltip="资产类型决定了 ref_type 必须匹配的字段; 编辑模式下不可修改"
          >
            <Select
              options={ASSET_TYPE_OPTIONS}
              disabled={isEdit}
              onChange={handleAssetTypeChange}
              placeholder="选择资产类型"
            />
          </Form.Item>

          {/* 关联信息 */}
          <Divider orientation="left">关联信息</Divider>
          <Form.Item
            name="ref_type"
            label="关联表名"
            rules={[{ required: true, message: '请选择关联表名' }]}
            tooltip={
              <div>
                <div>指向既有业务表名 (不加 FK 约束)</div>
                <div>通常与 asset_type 一致; test_data 可独立</div>
              </div>
            }
          >
            <Select
              options={REF_TYPE_OPTIONS}
              disabled={isEdit}
              placeholder="选择关联表名"
            />
          </Form.Item>

          <Form.Item
            name="ref_id"
            label="关联记录 ID"
            tooltip="0 表示纯索引资产 (如 test_data 无既有表); >0 时指向既有业务表记录 ID"
          >
            <InputNumber
              min={0}
              style={{ width: '100%' }}
              placeholder="0 表示纯索引资产"
              disabled={isEdit}
            />
          </Form.Item>

          {/* 描述信息 */}
          <Divider orientation="left">描述信息</Divider>
          <Form.Item name="summary" label="一句话摘要" tooltip="最多 500 字">
            <Input placeholder="例: 用户登录接口, 支持 SMS / 账号密码两种方式" maxLength={500} />
          </Form.Item>

          <Form.Item name="description" label="详细描述 (Markdown)">
            <TextArea
              rows={4}
              placeholder="详细说明该资产的功能 / 业务流程 / 注意事项"
            />
          </Form.Item>

          <Form.Item name="module" label="所属模块" tooltip="业务模块名, 便于筛选">
            <Input placeholder="例: 用户中心 / 订单管理" maxLength={100} />
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              placeholder="输入标签后按回车, 例: 高优先级 / P0"
              tokenSeparators={[',']}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item
            name="source"
            label="来源"
            tooltip="资产来源: 手工 / Swagger / Postman / HAR / 导入 / AI 生成"
          >
            <Select
              options={SOURCE_OPTIONS}
              disabled={isEdit}
              placeholder="选择来源"
            />
          </Form.Item>

          {/* 质量评分 (仅编辑模式) */}
          {isEdit && (
            <>
              <Divider orientation="left">质量评分</Divider>
              <Form.Item
                name="quality_score"
                label="质量评分 (0-100)"
                tooltip="由 AssetOptimizationAgent 自动计算; 也可手工调整"
              >
                <InputNumber min={0} max={100} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* 扩展元数据 */}
          <Divider orientation="left">扩展元数据 (JSON)</Divider>
          <Paragraph type="secondary" style={{ fontSize: 12 }}>
            各资产类型自定义字段, 如 API 接口的 method/path, 测试用例的 content_json 等。必须是合法 JSON 对象。
          </Paragraph>
          <TextArea
            value={extraMetadataStr}
            onChange={(e) => setExtraMetadataStr(e.target.value)}
            rows={8}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
            placeholder='{"method": "POST", "path": "/api/login"}'
          />

          {/* 提示 */}
          {isEdit && (
            <Alert
              style={{ marginTop: 16 }}
              type="info"
              showIcon
              message="编辑模式不可修改字段"
              description={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  asset_code / asset_type / ref_type / ref_id 为不可变字段, 创建后不能修改。
                  如需变更, 请新建资产并将旧资产标记为 deprecated。
                </Text>
              }
            />
          )}
          {!isEdit && assetType === 'test_data' && (
            <Alert
              style={{ marginTop: 16 }}
              type="info"
              showIcon
              message="test_data 是纯索引资产"
              description={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  ref_id 可保持为 0, 所有内容存放在 extra_metadata 中。常用于无既有业务表的测试数据。
                </Text>
              }
            />
          )}
        </Form>
      </Card>
    </div>
  );
}
