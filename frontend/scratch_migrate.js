import fs from 'fs';
import path from 'path';

const srcDir = path.join(process.cwd(), 'src');
const testsDir = path.join(process.cwd(), 'tests');

function walkDir(dir, callback) {
  fs.readdirSync(dir).forEach(f => {
    let dirPath = path.join(dir, f);
    let isDirectory = fs.statSync(dirPath).isDirectory();
    isDirectory ? walkDir(dirPath, callback) : callback(path.join(dir, f));
  });
}

walkDir(srcDir, function(filePath) {
  if (filePath.endsWith('.test.ts')) {
    const relPath = path.relative(srcDir, filePath);
    const destPath = path.join(testsDir, relPath);
    
    // Create dest dir
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    
    // Read content
    let content = fs.readFileSync(filePath, 'utf-8');
    
    // Replace imports. 
    // We need to count the depth of the file to go up to the project root, then down to src.
    // e.g. tests/components/common/foo.test.ts -> depth is 2 (components, common) -> prefix is '../../src/'
    // Actually, depth from `tests` to `src` is:
    // relPath: components/common/foo.test.ts
    const depth = relPath.split(path.sep).length - 1;
    const upPath = depth === 0 ? '../src/' : '../'.repeat(depth + 1) + 'src/';
    
    // Replace relative imports: from './...' or '../...'
    content = content.replace(/from\s+['"](\.[^'"]+)['"]/g, (match, p1) => {
      // p1 is the relative path from the old location in src
      // We resolve it relative to the old location
      const oldDir = path.dirname(filePath);
      const targetAbs = path.resolve(oldDir, p1);
      const destDir = path.dirname(destPath);
      let newRel = path.relative(destDir, targetAbs);
      if (!newRel.startsWith('.')) {
        newRel = './' + newRel;
      }
      return `from '${newRel}'`;
    });
    
    fs.writeFileSync(destPath, content);
    fs.unlinkSync(filePath);
    console.log(`Moved: ${relPath}`);
  }
});
