const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');

const app = express();
app.use(express.json({ limit: '10mb' }));

// Inicializar el cliente de WhatsApp
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', (qr) => {
    // Imprimir el código QR en la consola
    console.log('\n======================================================');
    console.log('¡ESCANEA ESTE CÓDIGO QR CON TU WHATSAPP!');
    console.log('======================================================\n');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    console.log('\n✅ Cliente de WhatsApp listo y conectado.');
});

client.initialize();

// Ruta para enviar mensajes
app.post('/send', async (req, res) => {
    const { chatId, message, imageUrl } = req.body;

    if (!chatId || !message) {
        return res.status(400).json({ error: 'Faltan parámetros (chatId, message)' });
    }

    try {
        let options = {};
        let content = message;

        // Si se proporciona una imagen por URL, adjuntarla
        if (imageUrl) {
            try {
                const media = await MessageMedia.fromUrl(imageUrl, { unsafeMime: true });
                options = { caption: message };
                content = media;
            } catch (err) {
                console.error('Error al descargar la imagen:', err.message);
                // Si falla la imagen, mandamos solo el texto
            }
        }

        await client.sendMessage(chatId, content, options);
        res.status(200).json({ success: true, message: 'Mensaje enviado' });
    } catch (error) {
        console.error('Error enviando mensaje:', error);
        res.status(500).json({ error: error.message });
    }
});

const PORT = 3000;
app.listen(PORT, () => {
    console.log(`\n🚀 Servidor API de WhatsApp escuchando en http://localhost:${PORT}`);
});
