-- UI Automation 数据库表结构设计
-- MySQL 8.0
-- 字符集: utf8mb4
-- 排序规则: utf8mb4_unicode_ci

-- 创建数据库
CREATE DATABASE IF NOT EXISTS `ui_automation` 
    DEFAULT CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE `ui_automation`;

-- ========================================
-- 1. 任务表 (task)
-- ========================================
CREATE TABLE `task` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_name` VARCHAR(255) NOT NULL COMMENT '任务名称',
    `status` ENUM('pending', 'processing', 'success', 'failed') NOT NULL DEFAULT 'pending' COMMENT '任务状态',
    `error_message` VARCHAR(1024) DEFAULT NULL COMMENT '错误信息',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_task_name` (`task_name`),
    INDEX `idx_status` (`status`),
    INDEX `idx_status_created` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='任务表';

-- ========================================
-- 2. 图片文件表 (image_file)
-- ========================================
CREATE TABLE `image_file` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_id` INT UNSIGNED NOT NULL COMMENT '任务ID',
    `original_filename` VARCHAR(255) NOT NULL COMMENT '原始文件名',
    `file_path` VARCHAR(512) NOT NULL COMMENT '文件存储路径',
    `file_size` BIGINT UNSIGNED NOT NULL COMMENT '文件大小（字节）',
    `file_type` VARCHAR(50) NOT NULL COMMENT '文件MIME类型',
    `width` INT UNSIGNED DEFAULT NULL COMMENT '图片宽度',
    `height` INT UNSIGNED DEFAULT NULL COMMENT '图片高度',
    `md5_hash` CHAR(32) DEFAULT NULL COMMENT '文件MD5哈希值',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_file_path` (`file_path`),
    INDEX `idx_task_id` (`task_id`),
    INDEX `idx_md5_hash` (`md5_hash`),
    INDEX `idx_task_created` (`task_id`, `created_at`),
    CONSTRAINT `fk_image_task` FOREIGN KEY (`task_id`) REFERENCES `task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='图片文件表';

-- ========================================
-- 3. 分析结果表 (analysis_result)
-- ========================================
CREATE TABLE `analysis_result` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_id` INT UNSIGNED NOT NULL COMMENT '任务ID',
    `agent_type` VARCHAR(50) NOT NULL COMMENT '使用的Agent类型',
    `page_type` VARCHAR(100) DEFAULT NULL COMMENT '页面类型（如：登录页、列表页）',
    `elements_json` TEXT COMMENT '识别的UI元素JSON',
    `interactions_json` TEXT COMMENT '交互操作JSON',
    `layout_json` TEXT COMMENT '布局信息JSON',
    `analysis_summary` TEXT COMMENT '分析总结',
    `raw_output` TEXT COMMENT 'Agent原始输出',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_id` (`task_id`),
    INDEX `idx_task_id` (`task_id`),
    INDEX `idx_agent_type` (`agent_type`),
    CONSTRAINT `fk_analysis_task` FOREIGN KEY (`task_id`) REFERENCES `task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分析结果表';

-- ========================================
-- 4. 脚本表 (script)
-- ========================================
CREATE TABLE `script` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_id` INT UNSIGNED NOT NULL COMMENT '任务ID',
    `script_type` VARCHAR(50) NOT NULL DEFAULT 'playwright' COMMENT '脚本类型',
    `script_content` TEXT NOT NULL COMMENT '脚本内容',
    `script_language` VARCHAR(20) NOT NULL DEFAULT 'python' COMMENT '脚本语言',
    `file_path` VARCHAR(512) DEFAULT NULL COMMENT '脚本文件保存路径',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_id` (`task_id`),
    INDEX `idx_task_id` (`task_id`),
    INDEX `idx_script_type` (`script_type`),
    CONSTRAINT `fk_script_task` FOREIGN KEY (`task_id`) REFERENCES `task` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='脚本表';
