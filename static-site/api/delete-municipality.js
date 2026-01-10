// Vercel Serverless Function: 自治体を削除
// GitHub APIを使用してtarget_urls.csvから削除

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

    const { id } = req.body;

    if (!id) {
        return res.status(400).json({ error: 'IDは必須です' });
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
                        'If-None-Match': '' // キャッシュ回避
                    }
                }
            );

            if (!getFileResponse.ok) {
                throw new Error('ファイルの取得に失敗しました');
            }

            const fileData = await getFileResponse.json();
            const currentContent = Buffer.from(fileData.content, 'base64').toString('utf-8');

            // 指定されたIDの行を削除
            const lines = currentContent.trim().split('\n');
            const header = lines[0];
            const filteredLines = lines.slice(1).filter(line => {
                const lineId = line.split(',')[0];
                return lineId !== id && lineId !== `"${id}"`;
            });

            // 削除対象が見つからない場合はエラー（ただしリトライ不要）
            if (filteredLines.length === lines.length - 1) {
                // 既に削除されている可能性もあるので、成功として扱うことも可能だが、
                // ここでは「見つからない」として返す（クライアント側で判断）
                if (attempts === 0) {
                    return res.status(404).json({ error: '指定されたIDが見つかりません' });
                } else {
                    // リトライ中に消えた場合は成功とみなす
                    return res.status(200).json({ success: true, message: `ID ${id}は既に削除されています` });
                }
            }

            const newContent = [header, ...filteredLines].join('\n');

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
                        message: `➖ 自治体削除: ID ${id}`,
                        content: Buffer.from(newContent).toString('base64'),
                        sha: fileData.sha
                    })
                }
            );

            if (updateResponse.status === 409) {
                console.warn(`Conflict detected (delete). Retrying... (${attempts + 1}/${MAX_RETRIES})`);
                attempts++;
                await new Promise(resolve => setTimeout(resolve, 1000));
                continue;
            }

            if (!updateResponse.ok) {
                const errorData = await updateResponse.json();
                throw new Error(errorData.message || '削除に失敗しました');
            }

            return res.status(200).json({
                success: true,
                message: `ID ${id}を削除しました`
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
