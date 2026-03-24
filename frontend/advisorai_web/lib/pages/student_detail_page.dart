import 'package:flutter/material.dart';

import 'student_workspace_page.dart';

class StudentDetailPage extends StatelessWidget {
  final String studentId;

  const StudentDetailPage({super.key, required this.studentId});

  @override
  Widget build(BuildContext context) {
    return StudentWorkspacePage(
      studentId: studentId,
      pageTitle: 'Advisor View',
      showBackButton: true,
    );
  }
}
