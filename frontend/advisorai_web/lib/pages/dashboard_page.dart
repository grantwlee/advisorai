import 'package:flutter/material.dart';

/// Student Dashboard Page
/// Displays:
/// - Student information (name, bulletin year)
/// - My Courses section (placeholder)
/// - AdvisorAI Chat section (placeholder)
/// Demonstrates component-based architecture with reusable widgets
class DashboardPage extends StatelessWidget {
  const DashboardPage({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    // Get username from navigation arguments (passed from login page)
    final String username =
        ModalRoute.of(context)?.settings.arguments as String? ?? 'Student';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        actions: [
          IconButton(
            icon: const Icon(Icons.api),
            tooltip: 'API Test',
            onPressed: () {
              Navigator.pushNamed(context, '/api-test');
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: () {
              Navigator.pushReplacementNamed(context, '/');
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Student Information Card
            _StudentInfoCard(username: username),
            const SizedBox(height: 24),

            // My Courses Section
            const _CoursesSection(),
            const SizedBox(height: 24),

            // AdvisorAI Chat Section
            const _AdvisorChatSection(),
          ],
        ),
      ),
    );
  }
}

/// Widget: Student Information Card
/// Shows student name and bulletin year (hardcoded mock data)
class _StudentInfoCard extends StatelessWidget {
  final String username;

  const _StudentInfoCard({required this.username});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            CircleAvatar(
              radius: 40,
              backgroundColor: Theme.of(context).colorScheme.primaryContainer,
              child: Text(
                username.isNotEmpty ? username[0].toUpperCase() : 'S',
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.bold,
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                ),
              ),
            ),
            const SizedBox(width: 20),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    username,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  const SizedBox(height: 8),
                  const _InfoRow(
                    icon: Icons.calendar_today,
                    label: 'Bulletin Year',
                    value: '2024-2025', // Hardcoded mock data
                  ),
                  const SizedBox(height: 4),
                  const _InfoRow(
                    icon: Icons.school,
                    label: 'Major',
                    value: 'Computer Science', // Hardcoded mock data
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

/// Helper widget for displaying icon + label + value rows
class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _InfoRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 16, color: Colors.grey[600]),
        const SizedBox(width: 8),
        Text(
          '$label: ',
          style: TextStyle(color: Colors.grey[600], fontSize: 14),
        ),
        Text(
          value,
          style: const TextStyle(fontWeight: FontWeight.w500, fontSize: 14),
        ),
      ],
    );
  }
}

/// Widget: My Courses Section
/// Placeholder for course listing functionality
/// Currently displays mock course data
class _CoursesSection extends StatelessWidget {
  const _CoursesSection();

  // Mock course data - will be replaced with API data later
  static const List<Map<String, String>> _mockCourses = [
    {
      'code': 'CSE 40622',
      'name': 'Software Engineering',
      'credits': '3',
      'status': 'In Progress',
    },
    {
      'code': 'MATH 20580',
      'name': 'Introduction to Linear Algebra',
      'credits': '3',
      'status': 'In Progress',
    },
    {
      'code': 'CSE 30151',
      'name': 'Theory of Computing',
      'credits': '3',
      'status': 'Completed',
    },
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.book, color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 8),
            Text(
              'My Courses',
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
            ),
          ],
        ),
        const SizedBox(height: 16),
        ..._mockCourses.map((course) => _CourseCard(course: course)),
      ],
    );
  }
}

/// Individual course card widget
class _CourseCard extends StatelessWidget {
  final Map<String, String> course;

  const _CourseCard({required this.course});

  @override
  Widget build(BuildContext context) {
    final isCompleted = course['status'] == 'Completed';

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: isCompleted
              ? Colors.green[100]
              : Theme.of(context).colorScheme.secondaryContainer,
          child: Icon(
            isCompleted ? Icons.check_circle : Icons.play_circle_outline,
            color: isCompleted
                ? Colors.green[700]
                : Theme.of(context).colorScheme.onSecondaryContainer,
          ),
        ),
        title: Text(
          course['name']!,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(course['code']!),
        trailing: Chip(
          label: Text('${course['credits']} credits'),
          backgroundColor:
              Theme.of(context).colorScheme.surfaceContainerHighest,
        ),
      ),
    );
  }
}

/// Widget: AdvisorAI Chat Section
/// Placeholder for AI chat functionality
/// Will integrate with Flask API later
class _AdvisorChatSection extends StatelessWidget {
  const _AdvisorChatSection();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(
              Icons.chat_bubble,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(width: 8),
            Text(
              'AdvisorAI Chat',
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                Icon(
                  Icons.smart_toy,
                  size: 64,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 16),
                Text(
                  'Chat with AdvisorAI',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Get personalized course recommendations and academic planning assistance',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.grey[600]),
                ),
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: () {
                    // TODO: Navigate to chat interface when implemented
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Chat feature coming soon!'),
                      ),
                    );
                  },
                  icon: const Icon(Icons.send),
                  label: const Text('Start Chat'),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
