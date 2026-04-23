const crypto = require('crypto');

/**
 * 生成Validation Code的函数
 * @param {string} companyId 企业ID
 * @param {string} hostId 主机标识
 * @param {string} version 版本号（可选）
 * @returns {string} Validation Code
 */
function generateValidationCode(companyId, hostId, version = null) {
	// 如果没有提供版本号，从package.json读取
	if (!version) {
		try {
			const packageJsonPath = require('path').join(process.cwd(), 'package.json');
			const packageJson = require('fs').readFileSync(packageJsonPath, 'utf8');
			const packageData = JSON.parse(packageJson);
			version = packageData.version || '001.0001';
		} catch (error) {
			console.warn('Failed to read version from package.json, using fallback:', error.message);
			version = '001.0001';
		}
	}
	
	// 硬编码的密钥（与license-validator.ts中的密钥保持一致）
	const secretKey = 'Arbore-License-Secret-Key-2024';
	
	// 组合数据 - 只使用发布版本主段，补足3位与后端一致（如 1.0.0 -> 001）
	const releaseVersion = (version.split('.')[0] || '001').padStart(3, '0');
	const data = `${companyId}-${hostId}-${releaseVersion}`;
	
	// 生成HMAC-SHA256签名
	const hmac = crypto.createHmac('sha256', secretKey);
	hmac.update(data);
	const signature = hmac.digest('hex');
	
	// 取前16位作为验证码
	return signature.substring(0, 16).toUpperCase();
}

/**
 * 验证Validation Code的函数
 * @param {string} companyId 企业ID
 * @param {string} hostId 主机标识
 * @param {string} version 版本号
 * @param {string} validationCode 要验证的验证码
 * @returns {boolean} 是否有效
 */
function validateValidationCode(companyId, hostId, version, validationCode) {
	const expectedCode = generateValidationCode(companyId, hostId, version);
	return expectedCode === validationCode.toUpperCase();
}

// 如果直接运行此文件，则提供命令行接口
if (require.main === module) {
	const args = process.argv.slice(2);
	
	if (args.length < 2) {
		console.log('Usage: node validation-code-generator.js <companyId> <hostId> [version]');
		console.log('Example: node validation-code-generator.js "12345678-1234-1234-1234-123456789012" "abc123def456"');
		console.log('Note: Version will be read from package.json if not provided');
		process.exit(1);
	}
	
	const companyId = args[0];
	const hostId = args[1];
	const version = args[2] || null; // 让函数从package.json读取
	
	const validationCode = generateValidationCode(companyId, hostId, version);
	
	console.log('=== Arbore Validation Code Generator ===');
	console.log(`Company ID: ${companyId}`);
	console.log(`Host ID: ${hostId}`);
	console.log(`Version: ${version}`);
	console.log(`Validation Code: ${validationCode}`);
	console.log('=========================================');
}

module.exports = {
	generateValidationCode,
	validateValidationCode
};
