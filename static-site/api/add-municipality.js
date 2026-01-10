// Vercel Serverless Function: 自治体を追加
// GitHub APIを使用してtarget_urls.csvに追記

module.exports = async function handler(req, res) {
    // CORSヘッダー
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const { municipality, url } = req.body;

    if (!municipality || !url) {
        return res.status(400).json({ error: '自治体名とURLは必須です' });
    }

    const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
    const REPO_OWNER = process.env.GITHUB_REPO_OWNER;
    const REPO_NAME = process.env.GITHUB_REPO_NAME;
    const FILE_PATH = 'target_urls.csv';

    if (!GITHUB_TOKEN || !REPO_OWNER || !REPO_NAME) {
        return res.status(500).json({ error: '環境変数が設定されていません' });
    }

    try {
        // 現在のファイル内容を取得
        const getFileResponse = await fetch(
            `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}`,
            {
                headers: {
                    'Authorization': `token ${GITHUB_TOKEN}`,
                    'Accept': 'application/vnd.github.v3+json'
                }
            }
        );

        if (!getFileResponse.ok) {
            throw new Error('ファイルの取得に失敗しました');
        }

        const fileData = await getFileResponse.json();
        const currentContent = Buffer.from(fileData.content, 'base64').toString('utf-8');

        // 新しいIDを生成（既存の最大ID + 1）
        const lines = currentContent.trim().split('\n');
        let maxId = 0;
        for (let i = 1; i < lines.length; i++) {
            const id = parseInt(lines[i].split(',')[0], 10);
            if (!isNaN(id) && id > maxId) {
                maxId = id;
            }
        }
        const newId = maxId + 1;

        // 新しい行を追加
        const newLine = `\n${newId},"${municipality}","${url}","",""`;
        const newContent = currentContent.trimEnd() + newLine;

        // ファイルを更新
        const updateResponse = await fetch(
            `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}`,
            {
                method: 'PUT',
                headers: {
                    'Authorization': `token ${GITHUB_TOKEN}`,
                    'Accept': 'application/vnd.github.v3+json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: `➕ 自治体追加: ${municipality}`,
                    content: Buffer.from(newContent).toString('base64'),
                    sha: fileData.sha
                })
            }
        );

        if (!updateResponse.ok) {
            const errorData = await updateResponse.json();
            throw new Error(errorData.message || '更新に失敗しました');
        }

        return res.status(200).json({
            success: true,
            message: `${municipality}を登録しました`,
            id: newId
        });

    } catch (error) {
        console.error('Error:', error);
        return res.status(500).json({ error: error.message });
    }
};
