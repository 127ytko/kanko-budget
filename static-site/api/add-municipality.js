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

    const MAX_RETRIES = 3;
    let attempts = 0;

    while (attempts < MAX_RETRIES) {
        try {
            // 現在のファイル内容を取得
            const getFileResponse = await fetch(
                `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}`,
                {
                    headers: {
                        'Authorization': `token ${GITHUB_TOKEN}`,
                        'Accept': 'application/vnd.github.v3+json',
                        // キャッシュを防ぐためにタイムスタンプを追加
                        'If-None-Match': ''
                    }
                }
            );

            if (!getFileResponse.ok) {
                throw new Error('ファイルの取得に失敗しました');
            }

            const fileData = await getFileResponse.json();
            const currentContent = Buffer.from(fileData.content, 'base64').toString('utf-8');

            // 既存の行を解析
            const lines = currentContent.trim().split('\n');
            const header = lines[0];
            let maxId = 0;
            let existingIndex = -1;
            let existingId = null;

            for (let i = 1; i < lines.length; i++) {
                const parts = lines[i].split(',');
                const id = parseInt(parts[0].replace(/"/g, ''), 10);
                const name = parts[1] ? parts[1].replace(/"/g, '').trim() : '';

                if (!isNaN(id) && id > maxId) {
                    maxId = id;
                }

                // 同名の自治体が存在するかチェック
                if (name === municipality) {
                    existingIndex = i;
                    existingId = id;
                }
            }

            let newContent;
            let actionMessage;
            let resultId;

            if (existingIndex !== -1) {
                // 既存の自治体のURLを更新
                lines[existingIndex] = `${existingId},"${municipality}","${url}","",""`;
                newContent = lines.join('\n');
                actionMessage = `🔄 自治体更新: ${municipality}`;
                resultId = existingId;
            } else {
                // 新しい自治体を追加
                const newId = maxId + 1;
                const newLine = `\n${newId},"${municipality}","${url}","",""`;
                newContent = currentContent.trimEnd() + newLine;
                actionMessage = `➕ 自治体追加: ${municipality}`;
                resultId = newId;
            }

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
                        message: actionMessage,
                        content: Buffer.from(newContent).toString('base64'),
                        sha: fileData.sha
                    })
                }
            );

            if (updateResponse.status === 409) {
                // 競合が発生した場合、少し待機してリトライ
                console.warn(`Conflict detected. Retrying... (${attempts + 1}/${MAX_RETRIES})`);
                attempts++;
                await new Promise(resolve => setTimeout(resolve, 1000)); // 1秒待機
                continue;
            }

            if (!updateResponse.ok) {
                const errorData = await updateResponse.json();
                throw new Error(errorData.message || '更新に失敗しました');
            }

            const isUpdate = existingIndex !== -1;
            return res.status(200).json({
                success: true,
                message: isUpdate ? `${municipality}のURLを更新しました` : `${municipality}を登録しました`,
                id: resultId,
                updated: isUpdate
            });

        } catch (error) {
            console.error('Error:', error);
            if (attempts === MAX_RETRIES - 1) {
                return res.status(500).json({ error: error.message });
            }
        }
        attempts++;
    }
};
