import { useEffect, useRef, useState } from 'react';
import { Button, Drawer, Form, Input, Radio, Select, Space, Upload, message } from 'antd';
import { createProject, fetchWorkspace, type Organization, type Project } from '@/services/workspace';
import { apiError, importGitRepo, importProjectArchive, importSampleRepo } from '@/services/projectExplorer';
import { setCurrentProjectId } from '@/pages/product/projectStore';
import { pickedFolderName, zipPickedFolder } from '@/utils/projectZip';

type Mode = 'create' | 'import';

export default function ProjectCreateDrawer({
  open,
  onClose,
  onCreated,
  mode = 'create',
  project,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (projectId: number, name: string) => void;
  mode?: Mode;
  project?: Project | null;
}) {
  const [form] = Form.useForm();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(false);
  const source = Form.useWatch('source', form);
  const folderRef = useRef<HTMLInputElement>(null);
  const intoExisting = mode === 'import' && !!project;
  const title = intoExisting ? `导入到「${project.name}」` : mode === 'import' ? '导入项目' : '新建项目';

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      name: project?.name || '',
      type: 'Web 应用',
      source: mode === 'import' ? 'github' : 'blank',
    });
    fetchWorkspace().then((data) => {
      const items = data?.organizations || [];
      setOrgs(items);
      const personal = items.find((item) => item.is_personal) || items[0];
      if (personal) form.setFieldValue('organization_id', personal.id);
    }).catch(() => undefined);
  }, [open, form, mode, project]);

  const ensureProject = async (values: any) => {
    if (project?.id) return { id: project.id, name: project.name };
    const created = await createProject(Number(values.organization_id), values.name, values.type);
    const id = created?.id || created?.project?.id;
    if (!id) throw new Error('创建成功但没有返回项目 ID');
    return { id, name: values.name };
  };

  const finish = async (file?: File) => {
    const fields = intoExisting ? ['source'] : ['name', 'organization_id', 'type', 'source'];
    if (source === 'github' || source === 'git') fields.push('repo_url');
    const values = await form.validateFields(fields);
    setLoading(true);
    try {
      const next = await ensureProject(values);
      setCurrentProjectId(next.id, next.name);
      if (source === 'sample') {
        await importSampleRepo(next.id);
        message.success('已导入示例项目');
      } else if ((source === 'github' || source === 'git') && values.repo_url) {
        await importGitRepo(next.id, values.repo_url);
        message.success('已从 Git 仓库导入');
      } else if (source === 'local' && file) {
        await importProjectArchive(next.id, file);
        message.success('已从本地项目导入');
      } else {
        message.success(mode === 'import' ? '项目已准备好，请选择导入方式' : '项目已创建');
        if (mode === 'import' && source !== 'blank') {
          setLoading(false);
          return;
        }
      }
      form.resetFields();
      onCreated(next.id, next.name);
    } catch (err: any) {
      message.error(apiError(err, mode === 'import' ? '导入失败' : '创建项目失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Drawer title={title} open={open} onClose={onClose} width={420} destroyOnClose>
      <Form form={form} layout="vertical" initialValues={{ type: 'Web 应用', source: mode === 'import' ? 'github' : 'blank' }}>
        {intoExisting ? null : (
          <>
            <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
              <Input placeholder="输入项目名称" />
            </Form.Item>
            <Form.Item name="organization_id" label="所属空间" rules={[{ required: true, message: '请选择空间' }]}>
              <Select options={orgs.map((item) => ({ value: item.id, label: item.name }))} />
            </Form.Item>
            <Form.Item name="type" label="项目类型">
              <Select options={['Web 应用', 'API 服务', '移动应用'].map((item) => ({ value: item, label: item }))} />
            </Form.Item>
          </>
        )}
        <Form.Item name="source" label={mode === 'import' ? '导入方式' : '项目来源'}>
          <Radio.Group>
            {mode === 'create' ? <Radio value="blank">空白项目</Radio> : null}
            <Radio value="github">GitHub</Radio>
            <Radio value="git">GitLab / Gitee / 其他 Git</Radio>
            <Radio value="local">本地文件夹 / ZIP</Radio>
            <Radio value="sample">示例项目</Radio>
          </Radio.Group>
        </Form.Item>
        {source === 'github' || source === 'git' ? (
          <Form.Item name="repo_url" label="仓库地址" rules={[{ required: true, message: '请输入仓库地址' }]}>
            <Input placeholder={source === 'github' ? 'https://github.com/org/repo' : 'https://gitlab.com/org/repo'} />
          </Form.Item>
        ) : null}
        {source === 'local' ? (
          <div>
            <p style={{ color: 'var(--text-muted)', margin: '0 0 8px' }}>可以选择本地文件夹，也可以继续上传 ZIP。会自动跳过 node_modules、.git 等目录。</p>
            <Space>
              <Button onClick={() => folderRef.current?.click()}>选择文件夹</Button>
              <Upload
                accept=".zip"
                maxCount={1}
                showUploadList={false}
                beforeUpload={(file) => {
                  void finish(file);
                  return false;
                }}
              >
                <Button>选择 ZIP</Button>
              </Upload>
            </Space>
            <input
              ref={(el) => {
                folderRef.current = el;
                if (el) {
                  el.setAttribute('webkitdirectory', '');
                  el.setAttribute('directory', '');
                }
              }}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                const files = event.target.files;
                event.target.value = '';
                if (!files?.length) return;
                if (!intoExisting && !form.getFieldValue('name')) {
                  form.setFieldValue('name', pickedFolderName(files));
                }
                setLoading(true);
                zipPickedFolder(files).then((zip) => finish(zip)).catch((err: any) => {
                  setLoading(false);
                  message.error(err?.message || '打包文件夹失败');
                });
              }}
            />
          </div>
        ) : null}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 24 }}>
          <Button onClick={onClose}>取消</Button>
          {source === 'local' ? null : (
            <Button type="primary" loading={loading} onClick={() => void finish()}>
              {mode === 'import' ? '开始导入' : '创建项目'}
            </Button>
          )}
        </div>
      </Form>
    </Drawer>
  );
}
