import React, { useState, forwardRef, useImperativeHandle } from 'react';
import {
  Card,
  Tabs,
  Form,
  Input,
  Button,
  Upload,
  message,
  Space,
  Tag,
  Row,
  Col,
  Alert,
} from 'antd';
import {
  InboxOutlined,
  PictureOutlined,
  FileTextOutlined,
  VideoCameraOutlined,
  DatabaseOutlined,
  LinkOutlined,
  EditOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';

const { TextArea } = Input;
const { Dragger } = Upload;

const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'];
const DOC_EXTS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.md', '.json', '.yaml', '.yml'];
const VIDEO_EXTS = ['.mp4', '.avi', '.mov', '.mkv'];
const SCHEMA_EXTS = ['.sql', '.ddl'];

export interface InputPanelData {
  text: string;
  urls: string;
  context: {
    system_name: string;
    business_background: string;
    test_scope: string;
    credentials: string;
    notes: string;
    special_requirements: string;
  };
  imageFiles: UploadFile[];
  docFiles: UploadFile[];
  videoFiles: UploadFile[];
  schemaFiles: UploadFile[];
}

export interface InputPanelHandle {
  getData: () => InputPanelData;
}

interface InputPanelProps {
  onStartAnalyze: () => void;
  analyzing: boolean;
}

const InputPanel = forwardRef<InputPanelHandle, InputPanelProps>(
  ({ onStartAnalyze, analyzing }, ref) => {
    const [form] = Form.useForm();
    const [activeTab, setActiveTab] = useState('text');
    const [imageFiles, setImageFiles] = useState<UploadFile[]>([]);
    const [docFiles, setDocFiles] = useState<UploadFile[]>([]);
    const [videoFiles, setVideoFiles] = useState<UploadFile[]>([]);
    const [schemaFiles, setSchemaFiles] = useState<UploadFile[]>([]);
    const [urls, setUrls] = useState('');
    const [context, setContext] = useState({
      system_name: '',
      business_background: '',
      test_scope: '',
      credentials: '',
      notes: '',
      special_requirements: '',
    });

    // Expose getData to parent
    useImperativeHandle(ref, () => ({
      getData: () => ({
        text: form.getFieldValue('requirement_text') || '',
        urls,
        context,
        imageFiles,
        docFiles,
        videoFiles,
        schemaFiles,
      }),
    }));

    const handleStart = () => {
      const textValue = form.getFieldValue('requirement_text') || '';
      if (!textValue && !imageFiles.length && !docFiles.length && !videoFiles.length && !schemaFiles.length && !urls) {
        message.warning('请至少提供一种输入');
        return;
      }
      onStartAnalyze();
    };

    // File upload handler - collect files without auto-uploading
    const beforeUpload = (file: File, setter: React.Dispatch<React.SetStateAction<UploadFile[]>>) => {
      setter((prev) => [
        ...prev,
        {
          uid: String(Date.now() + Math.random()),
          name: file.name,
          size: file.size,
          type: file.type,
          originFileObj: file as any,
        } as UploadFile,
      ]);
      return false;
    };

    const removeFile = (uid: string, setter: React.Dispatch<React.SetStateAction<UploadFile[]>>) => {
      setter((prev) => prev.filter((f) => f.uid !== uid));
    };

    const totalFiles = imageFiles.length + docFiles.length + videoFiles.length + schemaFiles.length;

    const tabItems = [
      {
        key: 'text',
        label: <span><EditOutlined /> 自然语言</span>,
        children: (
          <Form.Item name="requirement_text">
            <TextArea
              rows={8}
              placeholder={'请描述测试需求，支持Markdown格式\n例如：测试用户登录功能，需要验证用户名密码登录、记住密码、忘记密码等功能\n支持拖拽图片到此处'}
              allowClear
              showCount
              maxLength={5000}
            />
          </Form.Item>
        ),
      },
      {
        key: 'image',
        label: <span><PictureOutlined /> 图片 ({imageFiles.length})</span>,
        children: (
          <Dragger
            listType="picture-card"
            fileList={imageFiles}
            multiple
            accept={IMAGE_EXTS.join(',')}
            beforeUpload={(file) => { beforeUpload(file as unknown as File, setImageFiles); return false; }}
            onRemove={(file) => removeFile(file.uid, setImageFiles)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽图片到此处</p>
            <p className="ant-upload-hint">支持 PNG/JPG/JPEG/WEBP，可多选</p>
          </Dragger>
        ),
      },
      {
        key: 'document',
        label: <span><FileTextOutlined /> 文档 ({docFiles.length})</span>,
        children: (
          <Dragger
            fileList={docFiles}
            multiple
            accept={DOC_EXTS.join(',')}
            beforeUpload={(file) => { beforeUpload(file as unknown as File, setDocFiles); return false; }}
            onRemove={(file) => removeFile(file.uid, setDocFiles)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽文档到此处</p>
            <p className="ant-upload-hint">支持 PDF/Word/Excel/TXT/Markdown/Swagger/OpenAPI</p>
          </Dragger>
        ),
      },
      {
        key: 'video',
        label: <span><VideoCameraOutlined /> 视频 ({videoFiles.length})</span>,
        children: (
          <Dragger
            fileList={videoFiles}
            multiple
            accept={VIDEO_EXTS.join(',')}
            beforeUpload={(file) => { beforeUpload(file as unknown as File, setVideoFiles); return false; }}
            onRemove={(file) => removeFile(file.uid, setVideoFiles)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽视频到此处</p>
            <p className="ant-upload-hint">支持 MP4/AVI/MOV</p>
          </Dragger>
        ),
      },
      {
        key: 'schema',
        label: <span><DatabaseOutlined /> Schema ({schemaFiles.length})</span>,
        children: (
          <Dragger
            fileList={schemaFiles}
            multiple
            accept={SCHEMA_EXTS.join(',')}
            beforeUpload={(file) => { beforeUpload(file as unknown as File, setSchemaFiles); return false; }}
            onRemove={(file) => removeFile(file.uid, setSchemaFiles)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽数据库Schema文件</p>
            <p className="ant-upload-hint">支持 SQL/DDL/建表脚本</p>
          </Dragger>
        ),
      },
      {
        key: 'url',
        label: <span><LinkOutlined /> URL</span>,
        children: (
          <Input.TextArea
            rows={4}
            placeholder={'输入页面URL，每行一个\n例如：\nhttps://example.com/login\nhttps://example.com/register'}
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
          />
        ),
      },
      {
        key: 'context',
        label: <span><EditOutlined /> 附加上下文</span>,
        children: (
          <Row gutter={[16, 8]}>
            <Col span={12}>
              <Form.Item label="系统名称">
                <Input
                  placeholder="如：电商后台管理系统"
                  value={context.system_name}
                  onChange={(e) => setContext({ ...context, system_name: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="测试范围">
                <Input
                  placeholder="如：登录模块、订单模块"
                  value={context.test_scope}
                  onChange={(e) => setContext({ ...context, test_scope: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item label="业务背景">
                <TextArea
                  rows={2}
                  placeholder="业务背景描述"
                  value={context.business_background}
                  onChange={(e) => setContext({ ...context, business_background: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="账号密码">
                <Input.Password
                  placeholder="测试账号密码"
                  value={context.credentials}
                  onChange={(e) => setContext({ ...context, credentials: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="特殊要求">
                <Input
                  placeholder="特殊测试要求"
                  value={context.special_requirements}
                  onChange={(e) => setContext({ ...context, special_requirements: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item label="注意事项">
                <TextArea
                  rows={2}
                  placeholder="其他注意事项"
                  value={context.notes}
                  onChange={(e) => setContext({ ...context, notes: e.target.value })}
                />
              </Form.Item>
            </Col>
          </Row>
        ),
      },
    ];

    return (
      <Card
        title={
          <Space>
            <span>需求输入</span>
            {totalFiles > 0 && <Tag color="blue">{totalFiles} 个文件</Tag>}
            {urls && <Tag color="green">URL</Tag>}
          </Space>
        }
        extra={
          <Button
            type="primary"
            size="large"
            loading={analyzing}
            onClick={handleStart}
            disabled={analyzing}
          >
            {analyzing ? 'AI分析中...' : '开始AI分析'}
          </Button>
        }
      >
        <Form form={form} layout="vertical">
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            type="card"
          />
        </Form>

        {totalFiles === 0 && !form.getFieldValue('requirement_text') && !urls && (
          <Alert
            type="info"
            message="AI会自动选择解析方式，无需手动选择"
            description="支持自然语言、图片、文档、视频、数据库Schema、URL等多种输入方式，AI将自动理解需求并选择最佳分析策略"
            showIcon
            style={{ marginTop: 16 }}
          />
        )}
      </Card>
    );
  }
);

InputPanel.displayName = 'InputPanel';

export default InputPanel;
