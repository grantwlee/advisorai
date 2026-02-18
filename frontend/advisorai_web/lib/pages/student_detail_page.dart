import 'package:flutter/material.dart';
import '../services/api_service.dart';

class StudentDetailPage extends StatefulWidget {
  final String studentId;
  const StudentDetailPage({super.key, required this.studentId});

  @override
  State<StudentDetailPage> createState() => _StudentDetailPageState();
}

class _StudentDetailPageState extends State<StudentDetailPage> {
  final ApiService _api = ApiService();

  bool _isLoading = true;
  String? _error;
  Map<String, dynamic>? _student;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final data = await _api.getStudentDetail(widget.studentId);
      setState(() {
        _student = data;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Student Detail')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(
                    child: Text(
                      _error!,
                      style: const TextStyle(color: Colors.red),
                    ),
                  )
                : _student == null
                    ? const Center(child: Text('Student not found'))
                    : ListView(
                        children: [
                          Text(
                            _student?['name']?.toString() ?? '',
                            style: Theme.of(context).textTheme.headlineSmall,
                          ),
                          const SizedBox(height: 16),
                          _detailRow(
                            'Student ID',
                            _student?['student_id']?.toString() ?? '',
                          ),
                          _detailRow(
                            'Program',
                            _student?['program']?.toString() ?? '',
                          ),
                          _detailRow(
                            'Bulletin year',
                            _student?['bulletin_year']?.toString() ?? '',
                          ),
                          _detailRow(
                            'Email',
                            _student?['email']?.toString() ?? '',
                          ),
                          _detailRow(
                            'Phone',
                            _student?['phone']?.toString() ?? '',
                          ),
                        ],
                      ),
      ),
    );
  }
}
