import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // من أجل النسخ
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:animate_do/animate_do.dart';

class ChatScreen extends StatefulWidget {
  final String title;
  final String sysPrompt;
  const ChatScreen({Key? key, this.title = "المعلم الذكي", this.sysPrompt = "أنت مساعد تعليمي خبير، اشرح بوضوح وإيجاز."}) : super(key: key);

  @override
  _ChatScreenState createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _ctrl = TextEditingController();
  final ScrollController _scrollController = ScrollController(); 
  final List<Map<String, String>> _msgs = [];
  bool _loading = false;
  
  // تعريف الموديل والجلسة
  late final GenerativeModel _model;
  late final ChatSession _chatSession;
  final String apiKey = 'AIzaSyAP5WCqlWMylEUAjrCG8tn7KRE1kQd4mwE'; 

  @override
  void initState() {
    super.initState();
    // ✅ تم الحفاظ على اسم الموديل كما طلبته (gemini-2.5-pro)
    _model = GenerativeModel(model: 'gemini-2.5-pro', apiKey: apiKey);
    
    // بدء الجلسة مع السياق (System Prompt)
    _chatSession = _model.startChat(history: [
      Content.text(widget.sysPrompt)
    ]);
  }

  Future<void> _send() async {
    if (_ctrl.text.isEmpty) return;
    final text = _ctrl.text;
    
    setState(() { 
      _msgs.add({'role': 'user', 'text': text}); 
      _loading = true; 
    });
    _ctrl.clear();
    _scrollToBottom(); 

    try {
      // إرسال الرسالة والحفاظ على سياق المحادثة
      final response = await _chatSession.sendMessage(Content.text(text));
      
      setState(() {
        _msgs.add({'role': 'bot', 'text': response.text ?? "عذراً، لم أستطع تكوين إجابة."});
      });
    } catch (e) {
      setState(() {
         _msgs.add({'role': 'bot', 'text': "⚠️ حدث خطأ في الاتصال، يرجى المحاولة لاحقاً."});
      });
    } finally { 
      setState(() => _loading = false); 
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _showMessageOptions(String text) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: Icon(Icons.copy, color: Color(0xFF6C63FF)),
              title: Text("نسخ النص"),
              onTap: () {
                Clipboard.setData(ClipboardData(text: text));
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم النسخ بنجاح")));
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.auto_awesome, color: Colors.amber, size: 20),
            SizedBox(width: 8),
            Text(widget.title),
          ],
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: Icon(Icons.refresh),
            tooltip: "بدء محادثة جديدة",
            onPressed: () {
              setState(() { _msgs.clear(); });
              // يمكن إعادة تهيئة الجلسة هنا إذا أردت مسح الذاكرة تماماً
            },
          )
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _msgs.isEmpty 
            ? Center(
                child: FadeInUp(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center, 
                    children: [
                      Container(
                        padding: EdgeInsets.all(20),
                        decoration: BoxDecoration(color: Colors.grey.withOpacity(0.1), shape: BoxShape.circle),
                        child: Icon(Icons.chat_bubble_outline_rounded, size: 60, color: Colors.grey),
                      ),
                      SizedBox(height: 15),
                      Text("أنا جاهز لمساعدتك!\nاسألني أي شيء يخص دروسك.", textAlign: TextAlign.center, style: TextStyle(color: Colors.grey, height: 1.5))
                    ]
                  ),
                )
              )
            : ListView.builder(
              controller: _scrollController,
              padding: EdgeInsets.all(20),
              itemCount: _msgs.length,
              itemBuilder: (ctx, i) {
                final isUser = _msgs[i]['role'] == 'user';
                final msgText = _msgs[i]['text']!;
                
                return FadeInUp(
                  duration: Duration(milliseconds: 300),
                  child: Align(
                    alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                    child: GestureDetector(
                      onLongPress: () => _showMessageOptions(msgText),
                      child: Container(
                        margin: EdgeInsets.only(bottom: 15),
                        padding: EdgeInsets.symmetric(horizontal: 15, vertical: 10),
                        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.85),
                        decoration: BoxDecoration(
                          color: isUser ? Color(0xFF6C63FF) : (isDark ? Color(0xFF2A2A35) : Colors.white),
                          borderRadius: BorderRadius.only(
                            topLeft: Radius.circular(20),
                            topRight: Radius.circular(20),
                            bottomLeft: isUser ? Radius.circular(20) : Radius.circular(0),
                            bottomRight: isUser ? Radius.circular(0) : Radius.circular(20),
                          ),
                          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5, offset: Offset(0, 2))]
                        ),
                        child: isUser 
                          ? Text(msgText, style: TextStyle(color: Colors.white, fontSize: 15)) 
                          : MarkdownBody(
                              data: msgText, 
                              selectable: true,
                              styleSheet: MarkdownStyleSheet(
                                p: TextStyle(color: isDark ? Colors.white : Colors.black87, fontSize: 15, height: 1.5),
                                code: TextStyle(backgroundColor: isDark ? Colors.black54 : Colors.grey[200], fontFamily: 'monospace', fontSize: 13),
                                codeblockDecoration: BoxDecoration(
                                  color: isDark ? Colors.black54 : Colors.grey[200],
                                  borderRadius: BorderRadius.circular(8)
                                )
                              )
                            ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          if (_loading) 
            Padding(
              padding: const EdgeInsets.only(left: 20, bottom: 10),
              child: Align(alignment: Alignment.centerLeft, child: Text("جاري الكتابة...", style: TextStyle(color: Color(0xFF6C63FF), fontSize: 12, fontWeight: FontWeight.bold))),
            ),
          
          Container(
            padding: EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, -5))],
            ),
            child: Row(children: [
              Expanded(child: TextField(
                controller: _ctrl, 
                minLines: 1,
                maxLines: 4,
                decoration: InputDecoration(
                  hintText: "اكتب رسالتك...",
                  hintStyle: TextStyle(color: Colors.grey),
                  filled: true, 
                  fillColor: isDark ? Colors.grey[900] : Colors.grey[100], 
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(25), borderSide: BorderSide.none),
                  contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 12)
                )
              )),
              SizedBox(width: 10),
              GestureDetector(
                onTap: _loading ? null : _send,
                child: CircleAvatar(
                  radius: 24,
                  backgroundColor: _loading ? Colors.grey : Color(0xFF6C63FF), 
                  child: _loading 
                    ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                    : Icon(Icons.send_rounded, color: Colors.white, size: 20)
                ),
              )
            ]),
          )
        ],
      ),
    );
  }
}