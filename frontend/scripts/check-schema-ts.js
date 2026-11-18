const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const repoRoot = path.resolve(__dirname, '../..');
const schemaYml = path.join(repoRoot, 'schema.yml');
const currentDts = path.join(__dirname, '../src/app/core/api/schema.d.ts');
const tempDts = path.join(__dirname, '../src/app/core/api/schema.tmp.d.ts');

try {
  console.log('Generating fresh TypeScript types from schema.yml...');
  execSync(`npx openapi-typescript "${schemaYml}" -o "${tempDts}"`, { stdio: 'pipe' });

  const currentContent = fs.readFileSync(currentDts, 'utf8').trim();
  const tempContent = fs.readFileSync(tempDts, 'utf8').trim();

  if (currentContent !== tempContent) {
    console.error('ERROR: schema.d.ts is out of sync with schema.yml!');
    console.error('Run: npm run generate:api');
    process.exit(1);
  }

  console.log('SUCCESS: schema.d.ts is synchronized with schema.yml.');
} finally {
  if (fs.existsSync(tempDts)) {
    fs.unlinkSync(tempDts);
  }
}
