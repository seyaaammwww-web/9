import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:animate_do/animate_do.dart';

class ClassroomManager extends StatefulWidget {
  @override
  _ClassroomManagerState createState() => _ClassroomManagerState();
}

class _ClassroomManagerState extends State<ClassroomManager> {
  final _announcementController = TextEditingController();
  final TextEditingController _searchController = TextEditingController();
  String _searchQuery = "";

  void _postAnnouncement(BuildContext context) async {
    if (_announcementController.text.isEmpty) return;
    await FirebaseFirestore.instance.collection('announcements').add({
      'text': _announcementController.text,
      'author': "المعلم",
      'createdAt': FieldValue.serverTimestamp(),
    });
    _announcementController.clear();
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم نشر الإعلان")));
  }

  // دالة تأكيد الحذف
  void _confirmDelete(BuildContext context, DocumentReference docRef) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("تأكيد الحذف"),
        content: Text("هل أنت متأكد من حذف هذا الإعلان؟"),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text("إلغاء")),
          ElevatedButton(
            onPressed: () {
              docRef.delete();
              Navigator.pop(ctx);
            },
            child: Text("حذف"),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
          ),
        ],
      ),
    );
  }

  // دالة تعديل الإعلان
  void _showEditDialog(BuildContext context, DocumentSnapshot doc) {
    final TextEditingController editController = TextEditingController(text: doc['text']);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("تعديل الإعلان"),
        content: TextField(
          controller: editController,
          maxLines: 4,
          decoration: InputDecoration(labelText: "نص الإعلان"),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text("إلغاء")),
          ElevatedButton(
            onPressed: () {
              if (editController.text.isNotEmpty) {
                doc.reference.update({'text': editController.text});
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم التعديل")));
              }
            },
            child: Text("حفظ"),
            style: ElevatedButton.styleFrom(backgroundColor: Color(0xFF6C63FF), foregroundColor: Colors.white),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final cardColor = Theme.of(context).cardColor;
    final textColor = isDark ? Colors.white : Colors.black87;

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: Theme.of(context).scaffoldBackgroundColor,
        appBar: AppBar(
          title: Text("إدارة الفصل", style: TextStyle(color: textColor)),
          centerTitle: true,
          backgroundColor: Colors.transparent,
          elevation: 0,
          iconTheme: IconThemeData(color: textColor),
          bottom: TabBar(
            labelColor: Color(0xFF6C63FF),
            unselectedLabelColor: Colors.grey,
            indicatorColor: Color(0xFF6C63FF),
            tabs: [
              Tab(text: "الإعلانات"),
              Tab(text: "قائمة الطلاب"),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            // --- تاب الإعلانات (مع خيارات التعديل والحذف الآمن) ---
            Padding(
              padding: EdgeInsets.all(20),
              child: Column(
                children: [
                  TextField(
                    controller: _announcementController,
                    style: TextStyle(color: textColor),
                    decoration: InputDecoration(
                      hintText: "اكتب إعلاناً هاماً للفصل...",
                      hintStyle: TextStyle(color: Colors.grey),
                      filled: true,
                      fillColor: isDark ? Colors.grey[900] : Colors.grey[100],
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
                      suffixIcon: IconButton(icon: Icon(Icons.send, color: Color(0xFF6C63FF)), onPressed: () => _postAnnouncement(context)),
                    ),
                    maxLines: 3,
                  ),
                  SizedBox(height: 20),
                  Expanded(
                    child: StreamBuilder<QuerySnapshot>(
                      stream: FirebaseFirestore.instance.collection('announcements').orderBy('createdAt', descending: true).snapshots(),
                      builder: (context, snapshot) {
                        if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                        
                        return ListView.builder(
                          itemCount: snapshot.data!.docs.length,
                          itemBuilder: (ctx, i) {
                            var doc = snapshot.data!.docs[i];
                            return Card(
                              color: cardColor,
                              margin: EdgeInsets.only(bottom: 10),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                              child: ListTile(
                                leading: CircleAvatar(backgroundColor: Colors.orange.withOpacity(0.1), child: Icon(Icons.campaign, color: Colors.orange)),
                                title: Text(doc['text'], style: TextStyle(color: textColor, fontWeight: FontWeight.bold)),
                                subtitle: Text("من المعلم", style: TextStyle(color: Colors.grey)),
                                trailing: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    IconButton(
                                      icon: Icon(Icons.edit, size: 20, color: Color(0xFF6C63FF)),
                                      onPressed: () => _showEditDialog(context, doc),
                                    ),
                                    IconButton(
                                      icon: Icon(Icons.delete, size: 20, color: Colors.red[300]),
                                      onPressed: () => _confirmDelete(context, doc.reference),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        );
                      },
                    ),
                  )
                ],
              ),
            ),

            // --- تاب الطلاب (مع شريط البحث) ---
            Padding(
              padding: const EdgeInsets.all(20.0),
              child: Column(
                children: [
                  TextField(
                    controller: _searchController,
                    onChanged: (value) => setState(() => _searchQuery = value.toLowerCase()),
                    style: TextStyle(color: textColor),
                    decoration: InputDecoration(
                      hintText: "ابحث عن طالب بالاسم...",
                      hintStyle: TextStyle(color: Colors.grey),
                      prefixIcon: Icon(Icons.search, color: Color(0xFF6C63FF)),
                      filled: true,
                      fillColor: isDark ? Colors.grey[900] : Colors.grey[100],
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
                    ),
                  ),
                  SizedBox(height: 15),
                  Expanded(
                    child: StreamBuilder<QuerySnapshot>(
                      stream: FirebaseFirestore.instance.collection('users').where('role', isEqualTo: 'student').orderBy('name').snapshots(),
                      builder: (context, snapshot) {
                        if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                        
                        var filteredDocs = snapshot.data!.docs.where((doc) {
                          var name = (doc['name'] ?? "").toString().toLowerCase();
                          return name.contains(_searchQuery);
                        }).toList();

                        if (filteredDocs.isEmpty) {
                          return Center(child: Text("لا توجد نتائج مطابقة.", style: TextStyle(color: Colors.grey)));
                        }
                        
                        return ListView.builder(
                          itemCount: filteredDocs.length,
                          itemBuilder: (ctx, i) {
                            var doc = filteredDocs[i];
                            return Card(
                              color: cardColor,
                              margin: EdgeInsets.only(bottom: 10),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                              child: ListTile(
                                leading: CircleAvatar(
                                  backgroundColor: Color(0xFF6C63FF).withOpacity(0.1),
                                  child: Icon(Icons.person, color: Color(0xFF6C63FF))
                                ),
                                title: Text(doc['name'] ?? "طالب", style: TextStyle(color: textColor, fontWeight: FontWeight.bold)),
                                subtitle: Text("${doc['totalPoints'] ?? 0} نقطة XP", style: TextStyle(color: Colors.grey)),
                              ),
                            );
                          },
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}